# AIMETA P=LLM配置模式_模型配置与模型发现请求响应|R=LLM配置结构_模型列表结构|NR=不含业务逻辑|E=LLMConfigSchema,ModelListResponse|X=internal|A=Pydantic模式|D=pydantic|S=none|RD=./README.ai
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from ..llm_discovery.catalog import normalize_base_url


class LLMConfigBase(BaseModel):
    llm_provider_url: Optional[str] = Field(
        default=None,
        description="自定义 LLM 服务地址；缺少协议时会自动补 https://，以 # 结尾表示固定端点不做路径补全",
    )
    llm_provider_api_key: Optional[str] = Field(default=None, description="自定义 LLM API Key")
    llm_provider_model: Optional[str] = Field(default=None, description="自定义模型名称")

    @field_validator("llm_provider_url", mode="before")
    @classmethod
    def _normalize_url(cls, value):
        """统一归一化地址，避免 'api.deepseek.com' 这类写法被直接拒绝。"""

        if value is None:
            return None
        if isinstance(value, str):
            return normalize_base_url(value)
        # 兼容 pydantic 直接把 AnyUrl/HttpUrl 传入的场景
        return normalize_base_url(str(value))

    @field_validator("llm_provider_api_key", "llm_provider_model", mode="before")
    @classmethod
    def _strip_text(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class LLMConfigCreate(LLMConfigBase):
    pass


class LLMConfigRead(LLMConfigBase):
    user_id: int

    class Config:
        from_attributes = True


class ModelListRequest(BaseModel):
    """模型发现请求。

    只填 ``llm_provider_api_key`` 也可以：此时会使用默认的 OpenAI 地址。
    """

    llm_provider_url: Optional[str] = Field(default=None, description="LLM 服务地址")
    llm_provider_api_key: Optional[str] = Field(default=None, description="LLM API Key")
    provider: Optional[str] = Field(
        default=None,
        description="显式指定供应商标识（如 deepseek、siliconflow）；留空则按地址自动识别",
    )
    refresh: bool = Field(default=False, description="跳过缓存强制刷新")
    capabilities: Optional[List[str]] = Field(
        default=None,
        description="只返回包含指定能力标签的模型，例如 ['chat']",
    )

    @field_validator("llm_provider_url", mode="before")
    @classmethod
    def _normalize_url(cls, value):
        if value is None:
            return None
        return normalize_base_url(value) if isinstance(value, str) else normalize_base_url(str(value))

    @field_validator("llm_provider_api_key", mode="before")
    @classmethod
    def _strip_key(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class ModelInfoRead(BaseModel):
    """单个模型条目。"""

    id: str
    capabilities: List[str] = Field(default_factory=list, description="启发式推断的能力标签")
    owned_by: Optional[str] = None
    created: Optional[int] = None
    description: Optional[str] = None


class ModelListResponse(BaseModel):
    """模型发现结果。

    保留了 ``model_ids`` 字段以方便只关心模型名的调用方，
    同时通过 ``models`` 提供能力标签等附加信息。
    """

    provider: str
    provider_label: str
    base_url: Optional[str] = None
    endpoint: Optional[str] = Field(default=None, description="实际命中并返回模型列表的端点")
    models: List[ModelInfoRead] = Field(default_factory=list)
    model_ids: List[str] = Field(default_factory=list)
    total: int = 0
    cached: bool = False
    expires_in: int = Field(default=0, description="缓存剩余有效秒数")
    truncated: bool = Field(default=False, description="是否因数量上限被截断")
    elapsed_ms: int = 0
    latency_ms: Optional[int] = None
    attempts: List[str] = Field(default_factory=list, description="按顺序尝试过的端点")
    warnings: List[str] = Field(default_factory=list)
    capability_counts: Dict[str, int] = Field(default_factory=dict)


class ProviderInfoRead(BaseModel):
    """供应商预设，用于前端快速填充地址。"""

    id: str
    label: str
    kind: str
    default_base_url: Optional[str] = None
    docs_url: Optional[str] = None
    notes: Optional[str] = None
    supports_model_list: bool = Field(
        default=True,
        description="该供应商是否支持自动获取模型列表；为 false 时需手动输入模型名",
    )
