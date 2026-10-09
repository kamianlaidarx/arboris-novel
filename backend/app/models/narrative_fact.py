# AIMETA P=叙事事实模型_时序事实库|R=原子事实_有效期区间|NR=不含业务逻辑|E=NarrativeFact|X=internal|A=ORM模型|D=sqlalchemy|S=none|RD=./README.ai
"""
叙事事实（时序事实库）数据模型。

为什么需要这张表
----------------
Arboris 原本用一个 2000 字的 ``global_summary`` 承载全书上下文，每章让 LLM
重写一次。60 万字的书压缩进 2000 字、还反复重压，属于有损压缩，写到后面
必然丢失早期设定。

本表把「世界状态」改造成**带有效期区间**的原子事实，让「第 N 章时某实体的
状态是什么」变成一个可以精确查询的问题：

    SELECT * FROM narrative_facts
    WHERE project_id = :pid AND entity_id IN (...)
      AND valid_from <= :N AND (valid_until IS NULL OR valid_until >= :N);

受伤发生在第 5 章 → ``valid_from=5, valid_until=11``；
第 12 章痊愈 → 新事实 ``valid_from=12, valid_until=NULL``。
查询第 8 章得到「受伤」，查询第 13 章得到「已痊愈」——矛盾在结构上不可能发生。

依据：FactTrack (NAACL 2025) 用 7B 小模型 + 时间区间数据结构，做到了与裸
GPT-4 基线相当的矛盾检测水平，说明**数据结构的权重高于模型选择**。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base

#: 事实类型。与 CharacterState 的结构化字段保持一致，便于从一期状态派生。
FACT_TYPES = (
    "location",      # 人在哪
    "state",         # 身体/心理/存活状态
    "ability",       # 能力、实力等级
    "possession",    # 持有物品
    "relationship",  # 人物关系
    "knowledge",     # 谁知道什么（角色知识边界）
    "world",         # 世界规则、设定
)

#: 重要度。critical 的事实会进 P0 约束块。
IMPORTANCE_LEVELS = ("critical", "major", "minor")


class NarrativeFact(Base):
    """一条带有效期区间的原子事实。

    只增不改：新事实一律追加，旧事实的 ``valid_until`` 保持不变，
    除非调用方显式、且通过严格校验地将其失效（见 ``FactStore``）。
    """

    __tablename__ = "narrative_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("novel_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ---- 事实主体 ----
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, default="character")
    fact_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # ---- 事实内容 ----
    #: 一句话、可独立读懂的事实陈述，例如「左臂刀伤未愈」。
    content: Mapped[str] = mapped_column(String(512), nullable=False)

    # ---- 有效期区间（可查询的核心）----
    #: 从第几章开始成立。
    valid_from: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    #: 到第几章为止仍然成立；NULL 表示「至今仍然有效」。
    valid_until: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # ---- 溯源与元数据 ----
    importance: Mapped[str] = mapped_column(String(16), nullable=False, default="major")
    source_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 'llm' | 'manual' —— 人工录入的事实永不自动失效
    extracted_by: Mapped[str] = mapped_column(String(16), nullable=False, default="llm")
    #: 让「同一实体同一类型」的旧事实失效时，记录是哪条新事实取代了它。
    superseded_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("narrative_facts.id", ondelete="SET NULL"), nullable=True
    )
    extra: Mapped[Optional[dict]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # 主查询路径：按项目 + 实体取在期事实
        Index("ix_facts_lookup", "project_id", "entity_id", "valid_from", "valid_until"),
        # 区间扫描：找出某章所有在期事实
        Index("ix_facts_validity", "project_id", "valid_from", "valid_until"),
        # 失效判定的候选集：同一实体 + 同一类型
        Index("ix_facts_supersede", "project_id", "entity_id", "fact_type", "valid_until"),
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        span = f"{self.valid_from}..{self.valid_until if self.valid_until is not None else 'now'}"
        return f"<NarrativeFact {self.entity_id} {self.fact_type} {self.content!r} [{span}]>"
