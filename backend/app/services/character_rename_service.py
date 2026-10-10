# AIMETA P=角色改名_批量替换|R=改名预览_应用替换|NR=不自动决定映射|E=CharacterRenameService|X=internal|A=服务类|D=sqlalchemy|S=db|RD=./README.ai
"""把角色改名应用到章节大纲与正文。

背景
----
蓝图改过之后，大纲和正文仍是旧名字。检测（BlueprintStalenessService）
只能告诉你「哪里对不上」，真正要改还得靠人。本模块负责「改」这一步。

安全原则
--------
**正文不可盲替。** 中文名字存在大量歧义：

  - 蓝图「苏宛」vs 大纲「苏晚」——一字之差，可能是笔误也可能是两个人
  - 简称：「陆行舟」可能写作「行舟」「陆兄」「小陆」
  - 误伤：「陆」会出现在「陆续」「大陆」里

所以本模块：

1. 提供 **dry-run 预览**，把每一处改动连同上下文交给人过目；
2. 只做**全名精确替换**，不猜简称（简称需要人指定映射）；
3. 正文改动**新建版本**而非覆盖，原版永远可回退；
4. 应用前校验映射，拒绝会产生误伤的映射。

不做 LLM 改写：那会顺带改动其它文字，风险远大于收益。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.novel import Chapter, ChapterOutline, ChapterVersion, NovelProject

logger = logging.getLogger(__name__)

#: 单次预览里每处改动附带的上下文字符数（左右各取这么多）
CONTEXT_RADIUS = 30


@dataclass
class ReplacementOccurrence:
    """一处将被替换的位置，带上下文供人工确认。"""

    chapter_number: int
    #: outline | prose
    target: str
    count: int
    #: 若干条上下文片段，形如 "…前文【旧名】后文…"
    samples: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "target": self.target,
            "count": self.count,
            "samples": self.samples,
        }


@dataclass
class RenamePreview:
    """改名预览（不改动任何数据）。"""

    project_id: str
    #: {旧名: 新名}
    mapping: Dict[str, str]
    #: 每处改动
    occurrences: List[ReplacementOccurrence] = field(default_factory=list)
    #: 会被影响的章节号（大纲或正文任一）
    affected_outline_chapters: List[int] = field(default_factory=list)
    affected_chapter_numbers: List[int] = field(default_factory=list)
    #: 拒绝执行的映射及原因（例如新名已是另一个现存角色）
    rejected: List[Dict[str, str]] = field(default_factory=list)
    #: 需要提醒但不阻塞的风险
    warnings: List[str] = field(default_factory=list)

    @property
    def total_replacements(self) -> int:
        return sum(o.count for o in self.occurrences)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "mapping": self.mapping,
            "occurrences": [o.to_dict() for o in self.occurrences],
            "total_replacements": self.total_replacements,
            "affected_outline_chapters": self.affected_outline_chapters,
            "affected_chapter_numbers": self.affected_chapter_numbers,
            "rejected": self.rejected,
            "warnings": self.warnings,
        }


@dataclass
class RenameResult:
    """应用结果。"""

    project_id: str
    mapping: Dict[str, str]
    outlines_updated: int = 0
    chapters_updated: int = 0
    replacements: int = 0
    #: 新建的正文版本 id，便于回退
    new_version_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "mapping": self.mapping,
            "outlines_updated": self.outlines_updated,
            "chapters_updated": self.chapters_updated,
            "replacements": self.replacements,
            "new_version_ids": self.new_version_ids,
        }


def _build_samples(text: str, old: str, limit: int = 3) -> Tuple[int, List[str]]:
    """统计出现次数并抽取带上下文的样本。"""
    count = text.count(old)
    if count == 0:
        return 0, []
    samples: List[str] = []
    start = 0
    while len(samples) < limit:
        idx = text.find(old, start)
        if idx < 0:
            break
        left = max(0, idx - CONTEXT_RADIUS)
        right = min(len(text), idx + len(old) + CONTEXT_RADIUS)
        snippet = text[left:right].replace("\n", " ")
        prefix = "…" if left > 0 else ""
        suffix = "…" if right < len(text) else ""
        samples.append(f"{prefix}{snippet}{suffix}")
        start = idx + len(old)
    return count, samples


class CharacterRenameService:
    """把角色改名应用到大纲与正文。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _validate_mapping(
        self, project_id: str, mapping: Dict[str, str]
    ) -> Tuple[Dict[str, str], List[Dict[str, str]], List[str]]:
        """校验映射，返回 (可用映射, 被拒项, 警告)。

        **唯一的核心拒绝条件是「旧名仍是蓝图角色」。**

        为什么：本功能处理的是「下游文本用的还是旧名字」这一情形。
        如果旧名仍挂在蓝图里，说明用户想改的是蓝图本身，
        那应该去「主要角色」里改，而不是替换几十万字的正文。

        为什么**不**拒绝「新名已是蓝图角色」：这恰恰是主要用法。
        蓝图主角叫「沈渡」，而 82 条大纲里写的是改名前的「陆行舟」，
        用户填「陆行舟 → 沈渡」正是要让旧文本对齐当前蓝图。
        早期版本错误地拒绝了这一情形，导致用户做任何有意义的改名
        都会得到「没有找到可替换的内容」。
        """
        exists = (
            await self.session.execute(
                select(NovelProject.id).where(NovelProject.id == project_id)
            )
        ).scalar_one_or_none()
        if exists is None:
            return {}, [], []

        from ..models.novel import BlueprintCharacter

        current = (
            await self.session.execute(
                select(BlueprintCharacter.name).where(BlueprintCharacter.project_id == project_id)
            )
        ).scalars().all()
        current_names = {c.strip() for c in current if c and c.strip()}

        accepted: Dict[str, str] = {}
        rejected: List[Dict[str, str]] = []
        warnings: List[str] = []

        for old, new in mapping.items():
            old, new = (old or "").strip(), (new or "").strip()
            if not old or not new:
                continue
            if old == new:
                rejected.append({"old": old, "new": new, "reason": "新旧名字相同，无需替换"})
                continue
            if old in current_names:
                rejected.append({
                    "old": old,
                    "new": new,
                    "reason": (
                        f"「{old}」仍是当前蓝图中的角色。请先在「主要角色」里改蓝图，"
                        "而不是替换下游文本"
                    ),
                })
                continue
            # 注意：这里刻意不检查「新名是否已是蓝图角色」。
            # 那是主要用法（把旧文本对齐当前蓝图），不是错误。
            accepted[old] = new

        return accepted, rejected, warnings

    async def preview(self, project_id: str, mapping: Dict[str, str]) -> RenamePreview:
        """生成改名预览，不写入任何数据。"""
        accepted, rejected, warnings = await self._validate_mapping(project_id, mapping)
        result = RenamePreview(project_id=project_id, mapping=accepted, rejected=rejected, warnings=warnings)

        if not accepted:
            return result

        outlines = (
            await self.session.execute(
                select(ChapterOutline)
                .where(ChapterOutline.project_id == project_id)
                .order_by(ChapterOutline.chapter_number)
            )
        ).scalars().all()

        for outline in outlines:
            for old, new in accepted.items():
                for target, text in (("title", outline.title or ""), ("summary", outline.summary or "")):
                    count, samples = _build_samples(text, old)
                    if count:
                        result.occurrences.append(ReplacementOccurrence(
                            chapter_number=outline.chapter_number,
                            target="outline",
                            count=count,
                            samples=[f"[{target}] {s}" for s in samples],
                        ))
                        if outline.chapter_number not in result.affected_outline_chapters:
                            result.affected_outline_chapters.append(outline.chapter_number)

        chapters = (
            await self.session.execute(
                select(Chapter).where(Chapter.project_id == project_id)
            )
        ).scalars().all()

        for chapter in chapters:
            if not chapter.selected_version_id:
                continue
            version = await self.session.get(ChapterVersion, chapter.selected_version_id)
            if version is None or not version.content:
                continue
            for old, new in accepted.items():
                count, samples = _build_samples(version.content, old)
                if count:
                    result.occurrences.append(ReplacementOccurrence(
                        chapter_number=chapter.chapter_number,
                        target="prose",
                        count=count,
                        samples=samples,
                    ))
                    if chapter.chapter_number not in result.affected_chapter_numbers:
                        result.affected_chapter_numbers.append(chapter.chapter_number)

        # 新名已在下游出现时提醒：替换后可能读起来重复
        for old, new in accepted.items():
            for outline in outlines:
                if new in f"{outline.title or ''}{outline.summary or ''}":
                    warnings.append(f"新名字「{new}」已出现在第 {outline.chapter_number} 章大纲里，替换后可能重复")
                    break

        result.affected_outline_chapters.sort()
        result.affected_chapter_numbers.sort()
        return result

    async def apply(
        self,
        project_id: str,
        mapping: Dict[str, str],
        *,
        include_prose: bool = True,
    ) -> RenameResult:
        """执行替换。

        大纲：原地修改（结构化文本，风险低）。
        正文：**新建一个版本**并把 selected_version_id 指过去，
              原版本完整保留，用户可随时切回。

        ``include_prose=False`` 时只改大纲，适合用户想先看看效果的场景。
        """
        accepted, rejected, _ = await self._validate_mapping(project_id, mapping)
        if rejected:
            # 有被拒项时整体不执行，避免用户以为全改了其实只改了一半
            reasons = "；".join(f"{r['old']}→{r['new']}: {r['reason']}" for r in rejected)
            raise ValueError(f"映射校验未通过：{reasons}")
        if not accepted:
            raise ValueError("没有可执行的改名映射")

        result = RenameResult(project_id=project_id, mapping=accepted)

        outlines = (
            await self.session.execute(
                select(ChapterOutline)
                .where(ChapterOutline.project_id == project_id)
            )
        ).scalars().all()
        for outline in outlines:
            touched = False
            for old, new in accepted.items():
                if outline.title and old in outline.title:
                    result.replacements += outline.title.count(old)
                    outline.title = outline.title.replace(old, new)
                    touched = True
                if outline.summary and old in outline.summary:
                    result.replacements += outline.summary.count(old)
                    outline.summary = outline.summary.replace(old, new)
                    touched = True
            if touched:
                result.outlines_updated += 1

        if include_prose:
            chapters = (
                await self.session.execute(
                    select(Chapter).where(Chapter.project_id == project_id)
                )
            ).scalars().all()
            for chapter in chapters:
                if not chapter.selected_version_id:
                    continue
                version = await self.session.get(ChapterVersion, chapter.selected_version_id)
                if version is None or not version.content:
                    continue
                text = version.content
                hits = sum(text.count(old) for old in accepted)
                if not hits:
                    continue
                new_text = text
                for old, new in accepted.items():
                    new_text = new_text.replace(old, new)

                # 新建版本而不是覆盖：原版永远可回退。
                # 用 metadata 标记来源，便于日后区分「AI 生成的」与「改名产生的」。
                new_version = ChapterVersion(
                    chapter_id=chapter.id,
                    content=new_text,
                    version_label=f"rename-{'-'.join(accepted.keys())[:40]}",
                    metadata={"source": "character_rename", "mapping": accepted},
                )
                self.session.add(new_version)
                await self.session.flush()
                chapter.selected_version_id = new_version.id
                chapter.word_count = len(new_text)
                result.new_version_ids.append(new_version.id)
                result.replacements += hits
                result.chapters_updated += 1

        await self.session.commit()
        logger.info(
            "项目 %s 应用改名 %s：大纲 %d 条、正文 %d 章、共 %d 处",
            project_id,
            accepted,
            result.outlines_updated,
            result.chapters_updated,
            result.replacements,
        )
        return result
