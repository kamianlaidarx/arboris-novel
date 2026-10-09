# AIMETA P=事实库服务_时序事实读写|R=在期查询_安全失效_约束块渲染|NR=不含API路由|E=FactStore|X=internal|A=服务类|D=sqlalchemy|S=db|RD=./README.ai
"""
时序事实库（FactStore）。

核心操作
--------
1. ``facts_at(chapter)``  —— 查询「第 N 章时哪些事实成立」，这是生成时的约束来源。
2. ``record(...)``        —— 追加一条事实，可安全地让「同一实体+同一类型」的旧事实失效。
3. ``render_constraints`` —— 把在期事实渲染成注入提示词的 P0 约束块。

安全红线（务必不要放宽）
------------------------
Synapse 对生产环境 Graphiti/Zep + Neo4j（11 个项目）的审计发现：
**70% 被自动失效的事实仍然是真实的**，而且完全静默——无报错、写入返回成功。

根因是失效候选集用了空的 ``SearchFilters()``，于是候选 = 全图所有边按语义相似度
排序，**不要求与新事实共享实体**，然后交给一次 LLM 调用返回裸索引列表就提交。

因此本模块强制：
- 失效候选**只能**是「同一 project + 同一 entity_id + 同一 fact_type」；
- 且新事实必须**更具体**（更长、或显式声明 supersedes）才允许让旧的失效；
- 人工录入（``extracted_by="manual"``）的事实**永不自动失效**。

宁可保留过期事实（多召回一点噪声），也绝不静默删掉真事实。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.narrative_fact import FACT_TYPES, IMPORTANCE_LEVELS, NarrativeFact

logger = logging.getLogger(__name__)

#: 渲染约束块时每类事实最多带多少条，防止约束块本身膨胀成新的上下文负担。
MAX_FACTS_PER_ENTITY = 12
#: 单次渲染的总条数上限。
MAX_CONSTRAINT_FACTS = 60
#: 只有这些重要度会进入 P0 约束块。
_P0_IMPORTANCE = ("critical", "major")


@dataclass
class RecordOutcome:
    """``record`` 的结果，便于调用方断言与观测。"""

    fact: NarrativeFact
    superseded: List[NarrativeFact]
    created: bool

    @property
    def superseded_count(self) -> int:
        return len(self.superseded)


class FactStore:
    """一个项目的时序事实读写。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------ 读

    async def facts_at(
        self,
        project_id: str,
        chapter_number: int,
        *,
        entities: Optional[Sequence[str]] = None,
        fact_types: Optional[Sequence[str]] = None,
        include_minor: bool = False,
    ) -> List[NarrativeFact]:
        """返回「第 chapter_number 章时成立」的事实。

        区间语义：``valid_from <= N`` 且（``valid_until IS NULL`` 或 ``valid_until >= N``）。
        """
        stmt = select(NarrativeFact).where(
            NarrativeFact.project_id == project_id,
            NarrativeFact.valid_from <= chapter_number,
        )
        # NULL 表示至今有效
        stmt = stmt.where(
            or_(
                NarrativeFact.valid_until.is_(None),
                NarrativeFact.valid_until >= chapter_number,
            )
        )

        if entities:
            stmt = stmt.where(NarrativeFact.entity_id.in_(list(entities)))
        if fact_types:
            stmt = stmt.where(NarrativeFact.fact_type.in_(list(fact_types)))
        if not include_minor:
            stmt = stmt.where(NarrativeFact.importance.in_(_P0_IMPORTANCE))

        stmt = stmt.order_by(
            NarrativeFact.entity_id,
            NarrativeFact.fact_type,
            NarrativeFact.valid_from.desc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def facts_for_entity(
        self, project_id: str, entity_id: str, chapter_number: Optional[int] = None
    ) -> List[NarrativeFact]:
        """某实体的全部（或某章在期的）事实，用于界面展示与调试。"""
        if chapter_number is not None:
            return await self.facts_at(
                project_id, chapter_number, entities=[entity_id], include_minor=True
            )
        result = await self.session.execute(
            select(NarrativeFact)
            .where(
                NarrativeFact.project_id == project_id,
                NarrativeFact.entity_id == entity_id,
            )
            .order_by(NarrativeFact.valid_from.desc())
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------ 写

    async def record(
        self,
        *,
        project_id: str,
        entity_id: str,
        fact_type: str,
        content: str,
        chapter_number: int,
        entity_type: str = "character",
        importance: str = "major",
        extracted_by: str = "llm",
        supersede: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> RecordOutcome:
        """追加一条事实。

        默认**只增不改**：``supersede=False`` 时不会动任何既有事实。

        ``supersede=True`` 时，只有满足全部条件的旧事实才会被置为失效：
        - 同一 project、同一 entity_id、同一 fact_type；
        - ``valid_until IS NULL``（当前仍然有效）；
        - ``extracted_by != "manual"``（人工录入永不自动失效）；
        - ``valid_from < 本章``（不能失效同章或未来事实）；
        - 新内容**确实更具体**（见 ``_is_more_specific``）。

        任何一条不满足的候选都会被跳过并记录日志——宁可留下过期事实。
        """
        content = (content or "").strip()
        if not content:
            raise ValueError("事实内容不能为空")
        if fact_type not in FACT_TYPES:
            raise ValueError(f"未知的 fact_type: {fact_type!r}，允许值 {FACT_TYPES}")
        if importance not in IMPORTANCE_LEVELS:
            raise ValueError(f"未知的 importance: {importance!r}，允许值 {IMPORTANCE_LEVELS}")

        # 幂等：同章同实体的完全一致事实不重复写
        existing_same = await self.session.execute(
            select(NarrativeFact).where(
                NarrativeFact.project_id == project_id,
                NarrativeFact.entity_id == entity_id,
                NarrativeFact.fact_type == fact_type,
                NarrativeFact.content == content,
                NarrativeFact.valid_from == chapter_number,
            )
        )
        if (dup := existing_same.scalars().first()) is not None:
            return RecordOutcome(fact=dup, superseded=[], created=False)

        fact = NarrativeFact(
            project_id=project_id,
            entity_id=entity_id,
            entity_type=entity_type,
            fact_type=fact_type,
            content=content,
            valid_from=chapter_number,
            valid_until=None,
            importance=importance,
            source_chapter=chapter_number,
            extracted_by=extracted_by,
            extra=extra,
        )
        self.session.add(fact)
        await self.session.flush()

        superseded: List[NarrativeFact] = []
        if supersede:
            superseded = await self._supersede_previous(
                project_id=project_id,
                entity_id=entity_id,
                fact_type=fact_type,
                new_content=content,
                chapter_number=chapter_number,
                new_fact=fact,
            )

        return RecordOutcome(fact=fact, superseded=superseded, created=True)

    async def _supersede_previous(
        self,
        *,
        project_id: str,
        entity_id: str,
        fact_type: str,
        new_content: str,
        chapter_number: int,
        new_fact: NarrativeFact,
    ) -> List[NarrativeFact]:
        """在**严格限定的候选集**内让旧事实失效。"""
        candidate_result = await self.session.execute(
            select(NarrativeFact).where(
                NarrativeFact.project_id == project_id,
                NarrativeFact.entity_id == entity_id,
                NarrativeFact.fact_type == fact_type,
                NarrativeFact.valid_until.is_(None),
                NarrativeFact.valid_from < chapter_number,
                NarrativeFact.id != new_fact.id,
            )
        )
        candidates = list(candidate_result.scalars().all())
        if not candidates:
            return []

        superseded: List[NarrativeFact] = []
        for old in candidates:
            if old.extracted_by == "manual":
                logger.info(
                    "跳过人工录入的事实（永不自动失效）: id=%s %r", old.id, old.content
                )
                continue
            if not _is_more_specific(new_content, old.content):
                logger.info(
                    "跳过：新事实并不比旧事实更具体，拒绝失效 id=%s %r -> %r",
                    old.id,
                    old.content,
                    new_content,
                )
                continue

            old.valid_until = chapter_number - 1
            old.superseded_by_id = new_fact.id
            superseded.append(old)

        if superseded:
            logger.info(
                "已失效 %d 条旧事实: entity=%s type=%s chapter=%s",
                len(superseded),
                entity_id,
                fact_type,
                chapter_number,
            )
        return superseded

    # ------------------------------------------------------------- 渲染

    async def render_constraints(
        self,
        project_id: str,
        chapter_number: int,
        *,
        entities: Optional[Sequence[str]] = None,
    ) -> str:
        """把在期事实渲染成可注入提示词的约束块。

        返回空字符串表示没有任何在期事实（调用方应跳过该 prompt 区块）。
        """
        facts = await self.facts_at(project_id, chapter_number, entities=entities)
        if not facts:
            return ""

        return render_facts_block(facts, chapter_number)


def render_facts_block(facts: Sequence[NarrativeFact], chapter_number: int) -> str:
    """把事实列表渲染为紧凑的、以「约束」口吻表述的文本块。

    刻意不用叙事散文——Chroma 的实测表明，需要被精确遵守的状态应当是
    短小的结构化块，而不是长篇连贯散文（连贯散文反而会干扰检索）。
    """
    if not facts:
        return ""

    by_entity: Dict[str, List[NarrativeFact]] = {}
    for fact in facts[:MAX_CONSTRAINT_FACTS]:
        by_entity.setdefault(fact.entity_id, []).append(fact)

    lines: List[str] = []
    for entity_id in sorted(by_entity):
        entity_facts = by_entity[entity_id][:MAX_FACTS_PER_ENTITY]
        lines.append(f"【{entity_id}】")
        for fact in entity_facts:
            marker = "!" if fact.importance == "critical" else "-"
            since = f"（第{fact.valid_from}章起）" if fact.valid_from != chapter_number else ""
            lines.append(f"  {marker} {fact.content}{since}")

    header = (
        f"以下是截至第{chapter_number}章仍然成立的事实。"
        "这些是硬约束，不得与之矛盾；如需改变，必须在正文中写出改变的过程。"
    )
    return header + "\n" + "\n".join(lines)


def _is_more_specific(new_content: str, old_content: str) -> bool:
    """判断新事实是否**不是**旧事实的退化，从而可以被允许取代它。

    这里要防的是 Synapse 实测中占首位的误删模式：
    **一个更笼统的新事实把仍然为真的、更具体的旧事实顶掉**
    （例：关于「某个微服务」的陈述失效了关于「整个平台」的真事实）。

    因此判定只看「是否丢信息」，**不看字数**——状态改变往往是等长的：
    「左臂刀伤未愈」→「左臂刀伤已痊愈」是合法的状态转移，不能因为长度相同就拒绝。

    规则（按优先级）：
    1. 完全相同 → 不允许（没有变化）
    2. 新事实是旧事实的子串 → 更笼统，丢失了旧事实的限定信息 → 不允许
    3. 旧事实是新事实的子串 → 是细化 → 允许
    4. 其他情况 → 视为并列的事实更新（如地点 A → 地点 B），允许

    真正保护「不许静默删真事实」的机制不在这里，而在于：
    候选集被严格限定为「同实体 + 同类型」、人工事实豁免、
    以及默认 ``supersede=False`` 的只增不改策略。
    """
    new_text = (new_content or "").strip()
    old_text = (old_content or "").strip()
    if not new_text or not old_text:
        return False
    if new_text == old_text:
        return False
    # 新的是旧的子串 → 更笼统（丢掉了旧的限定成分）
    if new_text in old_text:
        return False
    # 旧的被新的完整包含 → 细化，允许
    if old_text in new_text:
        return True
    # 并列的事实更新
    return True


async def backfill_from_character_state(
    session: AsyncSession,
    project_id: str,
    chapter_number: int,
) -> int:
    """从一期写入的结构化 ``CharacterState`` 派生事实（零额外 LLM 调用）。

    一期已经把角色状态写进了结构化列，因此这里不需要再跑一次提取——
    直接把这些列翻译成时序事实即可，避免第二次 LLM 调用的成本与不稳定性。

    返回写入的事实条数。
    """
    from ..models.memory_layer import CharacterState

    result = await session.execute(
        select(CharacterState).where(
            CharacterState.project_id == project_id,
            CharacterState.chapter_number == chapter_number,
            CharacterState.character_name != "__all__",
        )
    )
    states = list(result.scalars().all())
    if not states:
        return 0

    store = FactStore(session)
    written = 0

    for state in states:
        name = state.character_name
        # (fact_type, content, importance)
        derived: List[tuple] = []

        if state.location:
            derived.append(("location", f"位于{state.location}", "major"))

        if state.health_status and state.health_status != "healthy":
            detail = state.health_status
            if state.injuries:
                injuries = "、".join(str(i) for i in state.injuries if i)
                if injuries:
                    detail = f"{state.health_status}（{injuries}）"
            derived.append(("state", f"身体状态：{detail}", "critical"))
        elif state.health_status == "healthy":
            derived.append(("state", "身体状态：健康", "minor"))

        if state.inventory:
            items = "、".join(str(i) for i in state.inventory if i)
            if items:
                derived.append(("possession", f"持有：{items}", "major"))

        if state.power_level:
            derived.append(("ability", f"实力：{state.power_level}", "major"))

        if state.relationship_changes and isinstance(state.relationship_changes, dict):
            for other, change in state.relationship_changes.items():
                if change:
                    derived.append(
                        ("relationship", f"与{other}的关系：{change}", "major")
                    )

        for fact_type, content, importance in derived:
            outcome = await store.record(
                project_id=project_id,
                entity_id=name,
                entity_type="character",
                fact_type=fact_type,
                content=content,
                chapter_number=chapter_number,
                importance=importance,
                extracted_by="llm",
                supersede=True,
            )
            if outcome.created:
                written += 1

    await session.flush()
    logger.info(
        "从结构化角色状态派生事实: project=%s chapter=%s 条数=%d",
        project_id,
        chapter_number,
        written,
    )
    return written
