# AIMETA P=供应商目录与识别规则|R=供应商识别_默认地址|NR=不含网络请求|E=detect_provider|X=internal|A=目录表+注册表|D=dataclasses|S=none|RD=./README.ai
"""供应商目录与识别规则。

旧实现用一长串 ``if "deepseek" in host`` 硬猜供应商，既容易误判又难以扩展。
这里改成**数据驱动**的规则表：

* 规则表只描述"什么样的地址属于哪个供应商"；
* 识别不到具体供应商时，回退到 :data:`ProviderKind.OPENAI_COMPATIBLE`
  这一通用协议族——这正是第三方中转站、自建网关、SiliconFlow、OpenRouter
  等绝大多数服务的工作方式。

需要接入新供应商时，只需在 ``_DESCRIPTORS`` 中追加一条记录，无需改动探测逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Optional, Sequence
from urllib.parse import urlsplit


class ProviderKind(str, Enum):
    """供应商协议族。"""

    OPENAI_COMPATIBLE = "openai-compatible"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"
    AZURE_OPENAI = "azure-openai"


@dataclass(frozen=True)
class ProviderDescriptor:
    """供应商描述。"""

    id: str
    label: str
    kind: ProviderKind
    default_base_url: Optional[str] = None
    # 识别规则：命中任意 host 片段即认为是该供应商
    host_fragments: Sequence[str] = ()
    # 识别规则：base_url 路径中包含任意片段即认为匹配（用于自建/反代场景）
    path_fragments: Sequence[str] = ()
    # 该协议族通常使用的模型列表端点后缀
    model_endpoints: Sequence[str] = ()
    docs_url: Optional[str] = None
    notes: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------- 目录

_DESCRIPTORS: Sequence[ProviderDescriptor] = (
    ProviderDescriptor(
        id="openai",
        label="OpenAI",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.openai.com/v1",
        host_fragments=("api.openai.com",),
        model_endpoints=("/models",),
        docs_url="https://platform.openai.com/docs/api-reference/models",
    ),
    ProviderDescriptor(
        id="anthropic",
        label="Anthropic Claude",
        kind=ProviderKind.ANTHROPIC,
        default_base_url="https://api.anthropic.com/v1",
        host_fragments=("api.anthropic.com", "anthropic.com"),
        model_endpoints=("/models",),
        docs_url="https://docs.anthropic.com/en/api/models-list",
        notes="Anthropic 官方已提供模型列表接口，使用 x-api-key 与 anthropic-version 头。",
    ),
    ProviderDescriptor(
        id="google",
        label="Google Gemini",
        kind=ProviderKind.GOOGLE,
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        host_fragments=("generativelanguage.googleapis.com",),
        model_endpoints=("/models",),
        docs_url="https://ai.google.dev/api/models",
    ),
    ProviderDescriptor(
        id="deepseek",
        label="DeepSeek",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.deepseek.com/v1",
        host_fragments=("api.deepseek.com", "deepseek.com"),
        docs_url="https://api-docs.deepseek.com/",
    ),
    ProviderDescriptor(
        id="moonshot",
        label="Moonshot 月之暗面",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.moonshot.cn/v1",
        host_fragments=("api.moonshot.cn", "moonshot.cn", "moonshot.ai"),
    ),
    ProviderDescriptor(
        id="zhipu",
        label="智谱 GLM",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        host_fragments=("open.bigmodel.cn", "bigmodel.cn", "zhipuai.cn"),
        notes="智谱开放平台不提供 /models 端点，需要在界面手动输入模型名。",
    ),
    ProviderDescriptor(
        id="dashscope",
        label="阿里云百炼 DashScope",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        host_fragments=("dashscope.aliyuncs.com",),
    ),
    ProviderDescriptor(
        id="siliconflow",
        label="SiliconFlow 硅基流动",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.siliconflow.cn/v1",
        host_fragments=("api.siliconflow.cn", "siliconflow.cn", "siliconflow.com"),
    ),
    ProviderDescriptor(
        id="openrouter",
        label="OpenRouter",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://openrouter.ai/api/v1",
        host_fragments=("openrouter.ai",),
    ),
    ProviderDescriptor(
        id="together",
        label="Together AI",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.together.xyz/v1",
        host_fragments=("api.together.xyz", "together.xyz", "together.ai"),
    ),
    ProviderDescriptor(
        id="groq",
        label="Groq",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.groq.com/openai/v1",
        host_fragments=("api.groq.com", "groq.com"),
    ),
    ProviderDescriptor(
        id="mistral",
        label="Mistral AI",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.mistral.ai/v1",
        host_fragments=("api.mistral.ai", "mistral.ai"),
    ),
    ProviderDescriptor(
        id="xai",
        label="xAI Grok",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://api.x.ai/v1",
        host_fragments=("api.x.ai", "x.ai"),
    ),
    ProviderDescriptor(
        id="volcengine",
        label="火山方舟 Ark",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        host_fragments=("ark.cn-beijing.volces.com", "volces.com"),
        notes="方舟使用推理接入点 ID 作为模型名，通常需要手动输入。",
    ),
    ProviderDescriptor(
        id="ollama",
        label="Ollama 本地",
        kind=ProviderKind.OLLAMA,
        default_base_url="http://localhost:11434",
        host_fragments=("localhost:11434", "127.0.0.1:11434", "ollama"),
        model_endpoints=("/api/tags",),
        docs_url="https://github.com/ollama/ollama/blob/main/docs/api.md",
        notes="本地模型列表走 /api/tags，需要使用内网地址访问权限。",
    ),
    ProviderDescriptor(
        id="azure-openai",
        label="Azure OpenAI",
        kind=ProviderKind.AZURE_OPENAI,
        host_fragments=(".openai.azure.com", "openai.azure.com"),
        docs_url="https://learn.microsoft.com/azure/ai-services/openai/",
        notes="Azure 不提供标准模型列表接口，部署名由用户自定义，需手动填写。",
    ),
    ProviderDescriptor(
        id="openai-compatible",
        label="OpenAI 兼容服务",
        kind=ProviderKind.OPENAI_COMPATIBLE,
        model_endpoints=("/models",),
        docs_url="https://platform.openai.com/docs/api-reference/models",
        notes="第三方中转站、自建网关与聚合平台，统一按 OpenAI 兼容协议探测。",
    ),
)

_BY_ID: Dict[str, ProviderDescriptor] = {item.id: item for item in _DESCRIPTORS}

_FALLBACK = _BY_ID["openai-compatible"]


# ------------------------------------------------------------------- 识别


def _normalized_host(url: str) -> str:
    parts = urlsplit(url if "://" in url else f"https://{url}")
    return (parts.netloc or "").lower()


def _normalized_path(url: str) -> str:
    parts = urlsplit(url if "://" in url else f"https://{url}")
    return (parts.path or "").lower()


def detect_provider(base_url: Optional[str]) -> ProviderDescriptor:
    """根据 base_url 识别供应商；识别不到则回退到 OpenAI 兼容协议族。

    识别优先看 host 片段，其次看路径片段（覆盖反代/自建域名场景），
    最后检查本地地址是否指向 Ollama。
    """

    if not base_url:
        return _BY_ID["openai"]

    host = _normalized_host(base_url)
    path = _normalized_path(base_url)

    if host in {"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"} or host.startswith(
        ("localhost:", "127.0.0.1:", "host.docker.internal:")
    ):
        # 本地端口 11434 是 Ollama 默认端口
        if host.endswith(":11434"):
            return _BY_ID["ollama"]

    for descriptor in _DESCRIPTORS:
        for fragment in descriptor.host_fragments:
            if fragment and fragment in host:
                return descriptor

    for descriptor in _DESCRIPTORS:
        for fragment in descriptor.path_fragments:
            if fragment and fragment in path:
                return descriptor

    return _FALLBACK


def get_provider(provider_id: str) -> Optional[ProviderDescriptor]:
    """按 ID 取供应商描述，未知 ID 返回 ``None``。"""

    if not provider_id:
        return None
    return _BY_ID.get(provider_id.strip().lower())


def list_providers() -> Sequence[ProviderDescriptor]:
    """返回全部已知供应商描述（含通用回退项）。"""

    return _DESCRIPTORS


def known_provider_ids() -> Iterable[str]:
    return tuple(item.id for item in _DESCRIPTORS)


def normalize_base_url(base_url: Optional[str]) -> Optional[str]:
    """归一化用户填写的地址。

    * 去除首尾空白与末尾斜杠；
    * 缺少协议时补 ``https://``（本地地址补 ``http://``）；
    * 保留用户以 ``#`` 结尾的"固定端点"语义（表示不再自动补全路径）。
    """

    if base_url is None:
        return None

    raw = base_url.strip()
    if not raw:
        return None

    pinned = raw.endswith("#")
    if pinned:
        raw = raw[:-1].strip()

    raw = raw.rstrip("/")
    if not raw:
        return None

    if "://" not in raw:
        lower = raw.lower()
        local_prefixes = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal", "[")
        scheme = "http" if lower.startswith(local_prefixes) else "https"
        raw = f"{scheme}://{raw}"

    return f"{raw}#" if pinned else raw


def is_local_or_private(base_url: str) -> bool:
    """判断地址是否指向内网/回环地址，用于安全开关校验。"""

    host = _normalized_host(base_url)
    if not host:
        return False
    bare_host = host.split(":")[0].strip("[]")
    if bare_host in {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}:
        return True
    if bare_host.endswith(".local") or bare_host.endswith(".internal"):
        return True
    if bare_host.startswith("10.") or bare_host.startswith("192.168."):
        return True
    if bare_host.startswith("172."):
        try:
            second = int(bare_host.split(".")[1])
        except (IndexError, ValueError):
            return False
        return 16 <= second <= 31
    if bare_host.startswith("169.254."):
        return True
    # IPv6 唯一本地地址（fc00::/7）与链路本地地址（fe80::/10）
    if bare_host.lower().startswith(("fc", "fd", "fe8")):
        return True
    return False
