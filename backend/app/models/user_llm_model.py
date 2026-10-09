# AIMETA P=用户多模型配置模型|R=多模型列表_活跃模型|NR=不含业务逻辑|E=UserLLMModel|X=internal|A=ORM模型|D=sqlalchemy|S=none|RD=./README.ai
"""
用户级多模型配置。

背景
----
原来的 ``llm_configs`` 表以 ``user_id`` 作主键，即「一个用户只能有一个模型」。
结果是：想换个模型问答，必须去设置页改配置——切回来还要再改一次。

本表把「用户 ↔ 模型」从 1:1 放宽到 1:N，并记录一个 ``is_active`` 作为默认模型，
从而支持「同一个窗口里直接切换模型」。

与旧表的关系
------------
``llm_configs`` 保留不动，继续作为「连接凭据」（URL + API Key）的唯一来源——
因为同一网关的多个模型共用一套凭据，没必要每个模型存一份 key。

本表只存「模型名」这一维度：
    llm_configs      : 1 行 / 用户  →  url + api_key（凭据）
    user_llm_models  : N 行 / 用户  →  model 名称（可切换的选项）

解析优先级（见 ``LLMService._resolve_llm_config``）：
    显式传入的 model > 本表 is_active=1 的模型 > 旧表 llm_configs 的模型 > 系统配置
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base


class UserLLMModel(Base):
    """用户保存的一个可选模型。"""

    __tablename__ = "user_llm_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: 网关返回的模型 id，例如 "deepseek-v4.1-flash"
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 展示用名称，未填则回退到 model_name
    display_name: Mapped[Optional[str]] = mapped_column(String(255))

    #: 是否为当前默认模型。同一用户至多一个为 True（由服务层保证）。
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: 用户手动排序用
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: 备注，方便区分用途（如「快」「便宜」「长文」）
    note: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="llm_models")

    __table_args__ = (
        # 同一用户不能重复收藏同一个模型
        UniqueConstraint("user_id", "model_name", name="uq_user_model"),
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        flag = "*" if self.is_active else ""
        return f"<UserLLMModel user={self.user_id} {self.model_name}{flag}>"
