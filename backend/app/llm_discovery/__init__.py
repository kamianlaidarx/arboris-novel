# AIMETA P=模型发现层_第三方大模型列表自动获取|R=模型发现_供应商识别_缓存|NR=不含业务生成逻辑|E=discover_models|X=internal|A=包|D=httpx|S=net,cache|RD=./README.ai
"""第三方大模型列表自动发现层。

本包把「如何获取一个供应商的模型列表」从业务服务中解耦出来：

* :mod:`models` 定义与传输无关的数据结构（模型信息、发现结果）。
* :mod:`errors` 定义分级的发现异常，供 API 层映射为可读错误。
* :mod:`catalog` 维护供应商目录与自动识别规则（不再依赖 URL 关键字硬猜）。
* :mod:`adapters` 实现各协议的发现适配器，OpenAI 兼容协议是主路径。
* :mod:`cache` 提供进程内 TTL 缓存，避免重复打第三方接口。
* :mod:`service` 负责编排：识别供应商 -> 逐个候选端点探测 -> 分类 -> 缓存。
"""

from .cache import ModelListCache, get_default_cache
from .catalog import (
    ProviderDescriptor,
    ProviderKind,
    detect_provider,
    get_provider,
    list_providers,
    normalize_base_url,
)
from .errors import (
    ModelDiscoveryError,
    NoModelListEndpointError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderUnreachableError,
)
from .models import Capability, ModelInfo, ModelListResult
from .service import ModelDiscoveryService, discover_models

__all__ = [
    "Capability",
    "ModelDiscoveryError",
    "ModelDiscoveryService",
    "ModelInfo",
    "ModelListCache",
    "ModelListResult",
    "NoModelListEndpointError",
    "ProviderAuthError",
    "ProviderDescriptor",
    "ProviderKind",
    "ProviderRateLimitError",
    "ProviderUnreachableError",
    "detect_provider",
    "discover_models",
    "get_default_cache",
    "get_provider",
    "list_providers",
    "normalize_base_url",
]
