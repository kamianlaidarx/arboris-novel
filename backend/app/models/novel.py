# AIMETA P=小说模型_项目和章节定义|R=小说表_章节表_版本表|NR=不含业务逻辑|E=Novel_Chapter_ChapterVersion|X=internal|A=ORM模型|D=sqlalchemy|S=none|RD=./README.ai
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base

# 自定义列类型：兼容跨数据库环境
BIGINT_PK_TYPE = BigInteger().with_variant(Integer, "sqlite")
LONG_TEXT_TYPE = Text().with_variant(LONGTEXT, "mysql")


class _MetadataAccessor:
    """Descriptor 用于将 `metadata` 访问重定向到 `metadata_`，且保持 Base.metadata 可用。"""

    def __get__(self, instance, owner):
        if instance is None:
            return Base.metadata
        return instance.metadata_

    def __set__(self, instance, value):
        instance.metadata_ = value


class NovelProject(Base):
    """小说项目主表，仅存放轻量级元数据。"""

    __tablename__ = "novel_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    initial_prompt: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship("User", back_populates="novel_projects")
    blueprint: Mapped[Optional["NovelBlueprint"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
    )
    conversations: Mapped[list["NovelConversation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="NovelConversation.seq"
    )
    characters: Mapped[list["BlueprintCharacter"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="BlueprintCharacter.position"
    )
    relationships_: Mapped[list["BlueprintRelationship"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="BlueprintRelationship.position"
    )
    outlines: Mapped[list["ChapterOutline"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ChapterOutline.chapter_number"
    )
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Chapter.chapter_number"
    )


class NovelConversation(Base):
    """对话记录表，存储概念阶段的连续对话。"""

    __tablename__ = "novel_conversations"

    id: Mapped[int] = mapped_column(BIGINT_PK_TYPE, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("novel_projects.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(LONG_TEXT_TYPE, nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    metadata = _MetadataAccessor()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[NovelProject] = relationship(back_populates="conversations")


class NovelBlueprint(Base):
    """蓝图主体信息（标题、风格等）。"""

    __tablename__ = "novel_blueprints"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("novel_projects.id", ondelete="CASCADE"), primary_key=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(255))
    target_audience: Mapped[Optional[str]] = mapped_column(String(255))
    genre: Mapped[Optional[str]] = mapped_column(String(128))
    style: Mapped[Optional[str]] = mapped_column(String(128))
    tone: Mapped[Optional[str]] = mapped_column(String(128))
    one_sentence_summary: Mapped[Optional[str]] = mapped_column(Text)
    full_synopsis: Mapped[Optional[str]] = mapped_column(LONG_TEXT_TYPE)
    world_setting: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    # 蓝图版本号：任何会改变「下游该长什么样」的修改都递增。
    # 大纲和章节生成时记录当时的 revision，之后比对就能知道哪些产物已过期。
    # 为什么用递增整数而不是时间戳：时间戳比较依赖时钟，且无法区分
    # 「同一秒内的两次修改」；整数只需等值比较，语义也直白。
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # 影响下游生成的那部分内容的指纹（角色/世界观/概要，不含书名等元信息）。
    # 保存时先比对指纹，只有内容真的变了才递增 revision——否则前端
    # 「打开编辑器→直接保存」就会把全部章节误标为过期，提示沦为噪音。
    content_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[NovelProject] = relationship(back_populates="blueprint")


class BlueprintCharacter(Base):
    """蓝图角色信息。"""

    __tablename__ = "blueprint_characters"

    id: Mapped[int] = mapped_column(BIGINT_PK_TYPE, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("novel_projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    identity: Mapped[Optional[str]] = mapped_column(String(255))
    personality: Mapped[Optional[str]] = mapped_column(Text)
    goals: Mapped[Optional[str]] = mapped_column(Text)
    abilities: Mapped[Optional[str]] = mapped_column(Text)
    relationship_to_protagonist: Mapped[Optional[str]] = mapped_column(Text)
    extra: Mapped[Optional[dict]] = mapped_column(JSON)
    position: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[NovelProject] = relationship(back_populates="characters")


class BlueprintRelationship(Base):
    """角色之间的关系。"""

    __tablename__ = "blueprint_relationships"

    id: Mapped[int] = mapped_column(BIGINT_PK_TYPE, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("novel_projects.id", ondelete="CASCADE"), nullable=False)
    character_from: Mapped[str] = mapped_column(String(255), nullable=False)
    character_to: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[NovelProject] = relationship(back_populates="relationships_")


class ChapterOutline(Base):
    """章节纲要，支持 metadata 存储导演脚本/节拍状态等信息。"""

    __tablename__ = "chapter_outlines"

    id: Mapped[int] = mapped_column(BIGINT_PK_TYPE, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("novel_projects.id", ondelete="CASCADE"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)  # 存储导演脚本/节拍状态
    metadata = _MetadataAccessor()
    # 生成这条大纲时的蓝图版本。与 NovelBlueprint.revision 不等即为过期。
    # 可空：历史数据没有这个信息，NULL 表示「未知」，不能当成过期来报。
    blueprint_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    project: Mapped[NovelProject] = relationship(back_populates="outlines")


class Chapter(Base):
    """章节正文状态，指向选中的版本。"""

    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(BIGINT_PK_TYPE, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("novel_projects.id", ondelete="CASCADE"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    real_summary: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="not_generated")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # 定稿状态：此前定稿走 fire-and-forget，失败只写日志，前端无从知晓。
    # finalize_status: pending | success | failed
    finalize_status: Mapped[Optional[str]] = mapped_column(String(32), default=None)
    finalize_error: Mapped[Optional[str]] = mapped_column(Text, default=None)
    selected_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapter_versions.id", ondelete="SET NULL"), nullable=True
    )
    # 生成这一章正文时的蓝图版本。与 NovelBlueprint.revision 不等即为过期。
    # 可空：历史数据没有这个信息，NULL 表示「未知」，不能当成过期来报。
    blueprint_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped[NovelProject] = relationship(back_populates="chapters")
    versions: Mapped[list["ChapterVersion"]] = relationship(
        "ChapterVersion",
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="ChapterVersion.created_at",
        primaryjoin="Chapter.id == ChapterVersion.chapter_id",
        foreign_keys="[ChapterVersion.chapter_id]",
    )
    selected_version: Mapped[Optional["ChapterVersion"]] = relationship(
        "ChapterVersion",
        foreign_keys=[selected_version_id],
        primaryjoin="Chapter.selected_version_id == ChapterVersion.id",
        post_update=True,
    )
    evaluations: Mapped[list["ChapterEvaluation"]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="ChapterEvaluation.created_at"
    )


class ChapterVersion(Base):
    """章节生成的不同版本文本。"""

    __tablename__ = "chapter_versions"

    id: Mapped[int] = mapped_column(BIGINT_PK_TYPE, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    version_label: Mapped[Optional[str]] = mapped_column(String(64))
    provider: Mapped[Optional[str]] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(LONG_TEXT_TYPE, nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    metadata = _MetadataAccessor()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chapter: Mapped[Chapter] = relationship(
        "Chapter",
        back_populates="versions",
        foreign_keys=[chapter_id],
    )
    evaluations: Mapped[list["ChapterEvaluation"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class ChapterEvaluation(Base):
    """章节评估记录。"""

    __tablename__ = "chapter_evaluations"

    id: Mapped[int] = mapped_column(BIGINT_PK_TYPE, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chapter_versions.id", ondelete="CASCADE"))
    decision: Mapped[Optional[str]] = mapped_column(String(32))
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    score: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chapter: Mapped[Chapter] = relationship(back_populates="evaluations")
    version: Mapped[Optional[ChapterVersion]] = relationship(back_populates="evaluations")
