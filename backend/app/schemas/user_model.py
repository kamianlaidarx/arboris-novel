# AIMETA P=用户多模型相关Schema|R=模型增删改_活跃切换|NR=不含业务逻辑|E=UserModelRead等|X=internal|A=Pydantic模型|D=pydantic|S=none|RD=./README.ai
"""用户多模型切换的请求/响应模型。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class UserModelRead(BaseModel):
    """一个可选模型的展示信息。"""

    id: int
    model_name: str
    display_name: Optional[str] = None
    is_active: bool = False
    sort_order: int = 0
    note: Optional[str] = None

    model_config = {"from_attributes": True}


class UserModelListResponse(BaseModel):
    """用户的模型列表。"""

    models: List[UserModelRead] = Field(default_factory=list)
    active_model: Optional[str] = Field(
        default=None, description="当前活跃模型名；为空表示未设置，将走系统默认"
    )


class UserModelCreate(BaseModel):
    """添加一个可选模型。"""

    model_name: str = Field(..., min_length=1, description="网关返回的模型 id")
    display_name: Optional[str] = Field(default=None, description="展示名，留空用模型名")
    note: Optional[str] = Field(default=None, description="备注，如「快」「长文」")
    make_active: bool = Field(default=False, description="添加后是否立即切换为当前模型")


class UserModelBulkCreate(BaseModel):
    """批量添加（用于「把网关返回的模型全部加入我的列表」）。"""

    model_names: List[str] = Field(..., min_length=1)


class UserModelActivate(BaseModel):
    """切换当前模型。"""

    model_id: Optional[int] = Field(default=None, description="按 id 切换")
    model_name: Optional[str] = Field(
        default=None, description="按名称切换；不存在时自动加入列表"
    )
