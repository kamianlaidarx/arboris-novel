# AIMETA P=章间交接契约模型|R=瞬时状态_场景承接|NR=不含业务逻辑|E=ChapterContract|X=internal|A=ORM模型|D=sqlalchemy|S=none|RD=./README.ai
"""
章间交接契约（ChapterContract）。

解决什么问题
------------
**事实库**（``NarrativeFact``）记录的是跨章持久的原子事实；
**契约**记录的是「章节结束那一刻的瞬时状态」——时间、地点、谁在场、正在做什么。

这两者不能互相替代。真实 bug 例（jarvis-write 的工程笔记）：

    上一章结尾：主角在黑暗中睡着了。
    下一章开头：主角茫然地盯着黑暗。

    根因：章间瞬时状态（时间/地点/伤势/当前动作/在场人物）从未被结构化，
          也没有任何环节负责校验它。唯一的机制是注入上一章最后 900 字
          并指望模型自己推断出状态。

事实库无法表达「章节结束的那一刻他在哪」，因为它按章记录持久事实。

设计要点
--------
1. **与原文并列注入**：契约供事实，原文供语感。Chroma 的实测表明，
   需要被精确遵守的状态应当是短小的结构化块；而语感需要真实散文。
   把两者分开，就不会互相干扰。
2. **规则优先，LLM 只处理歧义**：契约之间的明显矛盾（前一章「刚睡着」+
   无时间跳跃，下一章「醒着发呆」）可以用确定性规则抓出来，零 LLM 成本。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class ChapterContract(Base):
    """一章结束时的结构化瞬时状态。"""

    __tablename__ = "chapter_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("novel_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # ---- 时空 ----
    #: 故事内时间，自由文本，例如「第3天 深夜」。
    in_story_time: Mapped[Optional[str]] = mapped_column(String(128))
    #: 当前场景地点。
    location: Mapped[Optional[str]] = mapped_column(String(255))
    #: 下一章是否直接承接本章结尾（同一场景连续）。
    scene_continues: Mapped[bool] = mapped_column(Boolean, default=False)
    #: 时间推进提示：none | next_morning | days_later | ...
    #: 用于区分「合法的场景切换」与「矛盾」（如刚睡着就醒着发呆）。
    time_jump_hint: Mapped[Optional[str]] = mapped_column(String(64))

    # ---- 在场角色 ----
    #: [{name, location, physical, emotional, doing, knows[], unresolved_intent}]
    characters: Mapped[Optional[dict]] = mapped_column(JSON)

    # ---- 悬置线程 ----
    #: 本章结尾未解释的悬念，例如 ["庙外脚步声，未解释"]
    open_threads: Mapped[Optional[list]] = mapped_column(JSON)

    # ---- 原文（供语感，不是事实源）----
    prose_tail: Mapped[Optional[str]] = mapped_column(Text)

    # ---- 元数据 ----
    #: 'llm' | 'manual' —— 人工编辑过的契约不被自动覆盖
    extracted_by: Mapped[str] = mapped_column(String(16), default="llm")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("project_id", "chapter_number", name="uq_contract_project_chapter"),
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ChapterContract ch{self.chapter_number} @{self.location!r} {self.in_story_time!r}>"
