# AIMETA P=LLM配置模型_模型配置存储|R=LLM配置表|NR=不含配置逻辑|E=LLMConfig|X=internal|A=ORM模型|D=sqlalchemy|S=none|RD=./README.ai
from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base


class LLMConfig(Base):
    """用户自定义的 LLM 接入配置。

    这张表仍是「连接凭据」（url + api_key）的唯一来源——同一网关下的
    多个模型共用一套凭据。可切换的模型名列表放在 ``user_llm_models``。
    """

    __tablename__ = "llm_configs"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    llm_provider_url: Mapped[str | None] = mapped_column(Text())
    llm_provider_api_key: Mapped[str | None] = mapped_column(Text())
    llm_provider_model: Mapped[str | None] = mapped_column(Text())

    #: 是否已把 llm_provider_model 迁移进 user_llm_models。
    #: 用标记位而不是「列表是否为空」来判断，否则用户清空模型列表后，
    #: 旧模型会在下次读取时被重新播种回来。
    llm_models_seeded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="llm_config")
