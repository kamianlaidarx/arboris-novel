# AIMETA P=大纲重生成_范围与预览|R=按范围重生成_预览后应用|NR=不自动覆盖|E=OutlineRegenService|X=internal|A=服务类|D=sqlalchemy|S=db|RD=./README.ai
"""章节大纲的按范围重新生成（带预览）。

解决的问题
----------
原有的大纲生成只能**追加**：``start_chapter = 现有数量 + 1``，从最后一章
往后接。于是蓝图改完之后，早先生成的大纲既无法推翻重来，也无法只重生
某几章，更没法带「优化建议」去重生成——而「蓝图改了、大纲要重做」恰恰
是最常见的需求。

设计
----
**先生成、预览、再应用**，三步分离：

1. :meth:`generate` 只调用模型并解析结果，**不写数据库**；
2. 前端把新旧大纲并排展示给人确认；
3. :meth:`apply` 才真正写入。

为什么必须预览：一个项目可能有几十上百条大纲，一次性覆盖后旧内容就没了。
和角色改名一样，这类「批量且不可逆」的操作必须先让人过目。

**已有正文的章节要特别提示**：大纲改了但正文还是照旧大纲写的，
会产生新的不一致。系统不阻止，但必须让人知道。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.novel import Chapter, ChapterOutline, NovelProject
from ..utils.json_utils import remove_think_tags, sanitize_json_like_text, unwrap_markdown_json

logger = logging.getLogger(__name__)

#: 单次请求允许生成的最大章节数。
#: 一章大纲约需一次 LLM 调用，且模型上下文有限；超过这个量既慢又容易
#: 在后半段丢失一致性。需要更多时应分段进行。
MAX_CHAPTERS_PER_REQUEST = 30


@dataclass
class OutlineDraft:
    """一条待确认的大纲草稿。"""

    chapter_number: int
    title: str
    summary: str
    #: 该章当前已有的大纲（None 表示原本没有）
    existing_title: Optional[str] = None
    existing_summary: Optional[str] = None
    #: 该章是否已有正文（有则重生成大纲会造成新的不一致）
    has_prose: bool = False

    @property
    def is_new(self) -> bool:
        return self.existing_title is None and self.existing_summary is None

    @property
    def changed(self) -> bool:
        if self.is_new:
            return True
        return (self.title != (self.existing_title or "")) or (
            self.summary != (self.existing_summary or "")
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "title": self.title,
            "summary": self.summary,
            "existing_title": self.existing_title,
            "existing_summary": self.existing_summary,
            "has_prose": self.has_prose,
            "is_new": self.is_new,
            "changed": self.changed,
        }


@dataclass
class OutlineRegenPreview:
    """重生成预览（未写入任何数据）。"""

    project_id: str
    start_chapter: int
    end_chapter: int
    drafts: List[OutlineDraft] = field(default_factory=list)
    #: 会被覆盖的章节（原本已有大纲）
    overwritten_chapters: List[int] = field(default_factory=list)
    #: 已有正文、改大纲会造成不一致的章节
    chapters_with_prose: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    #: 模型原始返回，解析失败时便于排查
    raw_preview: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "start_chapter": self.start_chapter,
            "end_chapter": self.end_chapter,
            "drafts": [d.to_dict() for d in self.drafts],
            "overwritten_chapters": self.overwritten_chapters,
            "chapters_with_prose": self.chapters_with_prose,
            "warnings": self.warnings,
            "raw_preview": self.raw_preview,
        }


class OutlineRegenService:
    """按范围重新生成章节大纲。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _load_existing(self, project_id: str) -> Dict[int, ChapterOutline]:
        rows = (
            await self.session.execute(
                select(ChapterOutline).where(ChapterOutline.project_id == project_id)
            )
        ).scalars().all()
        return {o.chapter_number: o for o in rows}

    async def _load_prose_chapters(self, project_id: str) -> set:
        """有正文的章节号。只有选中了版本的章节才算「有正文」。"""
        rows = (
            await self.session.execute(
                select(Chapter.chapter_number).where(
                    Chapter.project_id == project_id,
                    Chapter.selected_version_id.is_not(None),
                )
            )
        ).scalars().all()
        return {int(n) for n in rows}

    def _build_prompt_input(
        self,
        blueprint_text: str,
        existing_outlines_text: str,
        start_chapter: int,
        num_chapters: int,
        instructions: str,
        keep_existing: bool,
    ) -> str:
        """拼装提示词输入。

        提示词模板要求 ``wait_to_generate`` 这个结构（见
        prompts/outline_generation.md 的输入约定），这里按其约定构造，
        而不是自己另发明一套字段名。
        """
        sections = [
            "[世界蓝图]",
            blueprint_text,
            "",
            "[已有章节大纲]",
            existing_outlines_text or "暂无",
            "",
            "[生成任务]",
        ]
        if keep_existing:
            sections.append(
                f"请重新生成第 {start_chapter} 到 {start_chapter + num_chapters - 1} 章的大纲，"
                "可以参考已有大纲的情节走向，但要在表达与结构上做改进。"
            )
        else:
            sections.append(
                f"请重新生成第 {start_chapter} 到 {start_chapter + num_chapters - 1} 章的大纲，"
                "不必受已有大纲限制，可以重新设计这一段的情节安排。"
            )

        if instructions.strip():
            sections += [
                "",
                "[用户的优化建议与限制]（优先级高于以上已有大纲）",
                instructions.strip(),
            ]

        sections += [
            "",
            "[输出要求]",
            "返回 JSON，包含一个 chapters 数组，每个元素含 chapter_number、title、summary。",
            f"chapter_number 必须从 {start_chapter} 开始连续递增，共 {num_chapters} 个。",
            json.dumps(
                {
                    "wait_to_generate": {
                        "start_chapter": start_chapter,
                        "num_chapters": num_chapters,
                    }
                },
                ensure_ascii=False,
            ),
        ]
        return "\n".join(sections)

    async def generate(
        self,
        project_id: str,
        *,
        start_chapter: int,
        num_chapters: int,
        instructions: str = "",
        keep_existing: bool = True,
        llm_service: Any,
        prompt_service: Any,
        user_id: Optional[int] = None,
    ) -> OutlineRegenPreview:
        """生成大纲草稿，**不写入数据库**。

        调用方拿到预览后交给用户确认，再调 :meth:`apply`。

        ``user_id`` 必须传：它决定用哪一套 LLM 凭据（用户级还是系统级）。
        早期版本在此写死 ``None``，于是回退到系统默认配置——而系统配置里的
        模型名在它指向的网关上并不存在，表现为「模型不存在（上游 404）」。
        这类错误很有误导性：用户明明配对了个人的模型与网关，
        问题却出在代码取错了配置来源。
        """
        if num_chapters <= 0:
            raise ValueError("生成数量必须大于 0")
        if num_chapters > MAX_CHAPTERS_PER_REQUEST:
            raise ValueError(
                f"单次最多生成 {MAX_CHAPTERS_PER_REQUEST} 章，"
                f"当前请求 {num_chapters} 章。请分段生成。"
            )
        if start_chapter < 1:
            raise ValueError("起始章节号必须大于等于 1")

        end_chapter = start_chapter + num_chapters - 1

        project = await self.session.get(NovelProject, project_id)
        if project is None:
            raise ValueError("项目不存在")

        from .novel_service import NovelService

        novel_service = NovelService(self.session)
        # 必须用 repo.get_by_id：它 eager-load 了 blueprint/characters/outlines
        # 等关系。直接 session.get 拿到的是「裸」对象，序列化时访问关系属性
        # 会触发懒加载，在异步上下文里抛 MissingGreenlet。
        loaded = await novel_service.repo.get_by_id(project_id)
        if loaded is None:
            raise ValueError("项目不存在")
        project_schema = await novel_service._serialize_project(loaded)
        blueprint_text = json.dumps(
            project_schema.blueprint.model_dump(), ensure_ascii=False, indent=2
        )

        existing = await self._load_existing(project_id)
        existing_outlines_text = "\n".join(
            f"第{n}章 - {o.title}: {o.summary}"
            for n, o in sorted(existing.items())
        )

        prompt_input = self._build_prompt_input(
            blueprint_text,
            existing_outlines_text,
            start_chapter,
            num_chapters,
            instructions,
            keep_existing,
        )

        outline_prompt = await prompt_service.get_prompt("outline_generation")
        if not outline_prompt:
            raise ValueError("未配置大纲生成提示词")

        raw = await llm_service.get_llm_response(
            system_prompt=outline_prompt,
            conversation_history=[{"role": "user", "content": prompt_input}],
            temperature=0.7,
            user_id=user_id,
        )

        cleaned = remove_think_tags(raw)
        normalized = unwrap_markdown_json(cleaned)
        sanitized = sanitize_json_like_text(normalized)
        try:
            data = json.loads(sanitized)
        except json.JSONDecodeError as exc:
            logger.error(
                "大纲重生成解析失败: project=%s error=%s\n原文: %s",
                project_id,
                exc,
                raw[:800],
            )
            raise ValueError(f"AI 返回的内容不是合法 JSON：{exc}") from exc

        chapters = data.get("chapters") or []
        if not isinstance(chapters, list) or not chapters:
            raise ValueError("AI 未返回任何章节大纲")

        prose_chapters = await self._load_prose_chapters(project_id)

        preview = OutlineRegenPreview(
            project_id=project_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            raw_preview=raw[:2000],
        )

        for item in chapters:
            if not isinstance(item, dict):
                continue
            try:
                number = int(item.get("chapter_number"))
            except (TypeError, ValueError):
                continue
            old = existing.get(number)
            draft = OutlineDraft(
                chapter_number=number,
                title=str(item.get("title") or "").strip(),
                summary=str(item.get("summary") or "").strip(),
                existing_title=old.title if old else None,
                existing_summary=old.summary if old else None,
                has_prose=number in prose_chapters,
            )
            preview.drafts.append(draft)
            if old is not None:
                preview.overwritten_chapters.append(number)
            if draft.has_prose:
                preview.chapters_with_prose.append(number)

        if not preview.drafts:
            raise ValueError("AI 返回的章节大纲缺少有效的 chapter_number")

        preview.drafts.sort(key=lambda d: d.chapter_number)
        preview.overwritten_chapters.sort()
        preview.chapters_with_prose.sort()

        if preview.chapters_with_prose:
            preview.warnings.append(
                f"第 {'、'.join(str(n) for n in preview.chapters_with_prose[:10])} 章已有正文，"
                "改写大纲后正文会与新大纲不一致，建议之后一并重新生成正文。"
            )
        if preview.overwritten_chapters:
            preview.warnings.append(
                f"将覆盖 {len(preview.overwritten_chapters)} 条已有大纲，"
                "确认前请先对比新旧内容。"
            )

        return preview

    async def apply(self, project_id: str, drafts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """把确认后的大纲草稿写入数据库。"""
        from .novel_service import NovelService

        novel_service = NovelService(self.session)
        revision = await novel_service.get_blueprint_revision(project_id)

        updated = 0
        created = 0
        for item in drafts:
            try:
                number = int(item.get("chapter_number"))
            except (TypeError, ValueError):
                continue
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not title and not summary:
                continue

            existing = (
                await self.session.execute(
                    select(ChapterOutline).where(
                        ChapterOutline.project_id == project_id,
                        ChapterOutline.chapter_number == number,
                    )
                )
            ).scalars().first()

            if existing is None:
                self.session.add(
                    ChapterOutline(
                        project_id=project_id,
                        chapter_number=number,
                        title=title,
                        summary=summary,
                        blueprint_revision=revision,
                    )
                )
                created += 1
            else:
                existing.title = title
                existing.summary = summary
                # 这批大纲是照当前蓝图写的，标记版本号，
                # 否则它们会一直被当成「过期」。
                existing.blueprint_revision = revision
                updated += 1

        await self.session.commit()
        logger.info(
            "项目 %s 应用大纲重生成：新增 %d 条、覆盖 %d 条", project_id, created, updated
        )
        return {"created": created, "updated": updated}
