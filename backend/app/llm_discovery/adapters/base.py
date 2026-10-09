# AIMETA P=适配器基础设施|R=HTTP客户端构造_模型能力分类|NR=不含具体协议实现|E=ModelListAdapter,classify_model|X=internal|A=Protocol+工具函数|D=httpx|S=net|RD=./README.ai
"""适配器公共基础设施：上下文、协议接口、能力分类。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence

import httpx

from ..catalog import ProviderDescriptor
from ..errors import (
    ModelDiscoveryError,
    NoModelListEndpointError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderUnreachableError,
)
from ..models import MAX_CAPABILITIES_PER_MODEL, Capability

logger = logging.getLogger(__name__)


def build_async_client(
    *,
    timeout: float = 20.0,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    verify: bool = True,
) -> httpx.AsyncClient:
    """构造探测用的 httpx 客户端。

    所有适配器都通过这里创建客户端，测试可注入 ``httpx.MockTransport``
    以离线验证真实的请求构造与响应解析逻辑。
    """

    kwargs: Dict[str, Any] = {
        "timeout": httpx.Timeout(timeout, connect=min(10.0, timeout)),
        "follow_redirects": True,
        "verify": verify,
    }
    if transport is not None:
        kwargs["transport"] = transport
    headers = {
        "User-Agent": "arboris-novel/model-discovery",
        "Accept": "application/json",
    }
    return httpx.AsyncClient(headers=headers, **kwargs)


@dataclass
class DiscoverContext:
    """一次发现请求的上下文。"""

    base_url: Optional[str]
    api_key: Optional[str]
    provider: ProviderDescriptor
    timeout: float = 20.0
    transport: Optional[httpx.AsyncBaseTransport] = None
    verify_tls: bool = True
    extra_headers: Dict[str, str] = field(default_factory=dict)
    # 适配器可写入的警告收集器
    warnings: List[str] = field(default_factory=list)

    def client(self) -> httpx.AsyncClient:
        return build_async_client(
            timeout=self.timeout,
            transport=self.transport,
            verify=self.verify_tls,
        )


class ModelListAdapter(Protocol):
    """模型列表适配器协议。"""

    async def fetch(self, ctx: DiscoverContext) -> tuple[Optional[str], List[Any], List[str]]:
        """返回 ``(endpoint, 原始条目列表, 尝试记录)``。

        原始条目是适配器解析后的轻量结构，由服务层统一转换为 :class:`ModelInfo`。
        """
        ...


# --------------------------------------------------------------- 状态码映射


def raise_for_status(
    response: httpx.Response,
    *,
    provider: str,
    endpoint: str,
) -> None:
    """把 HTTP 状态码映射为分级异常。"""

    status = response.status_code
    if status < 400:
        return

    detail = _extract_error_detail(response)

    if status in (401, 403):
        raise ProviderAuthError(provider=provider, endpoint=endpoint, status_code=status, details=detail)
    if status == 404:
        raise NoModelListEndpointError(provider=provider, endpoint=endpoint, status_code=status, details=detail)
    if status == 429:
        raise ProviderRateLimitError(provider=provider, endpoint=endpoint, status_code=status, details=detail)
    if status >= 500:
        raise ProviderServerError(provider=provider, endpoint=endpoint, status_code=status, details=detail)
    raise ModelDiscoveryError(
        f"获取模型列表失败（HTTP {status}）",
        hint="请确认该地址支持模型列表查询，或改为手动输入模型名称。",
        provider=provider,
        endpoint=endpoint,
        status_code=status,
        details=detail,
    )


def _extract_error_detail(response: httpx.Response) -> Optional[str]:
    """从第三方错误响应中提取可读信息。"""

    try:
        payload = response.json()
    except Exception:
        text = (response.text or "").strip()
        return text[:300] or None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("message_zh")
            if message:
                return str(message)[:300]
        if isinstance(error, str):
            return error[:300]
        for key in ("message", "msg", "detail", "error_description"):
            if payload.get(key):
                return str(payload[key])[:300]
    return None


def wrap_request_error(exc: Exception, *, provider: str, endpoint: str) -> ModelDiscoveryError:
    """把 httpx 网络异常映射为分级异常。"""

    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return ProviderUnreachableError(
            "连接该 API 地址超时",
            hint="请确认地址可访问且网络通畅；自建网关请检查反代与端口。",
            provider=provider,
            endpoint=endpoint,
            details=str(exc),
        )
    if isinstance(exc, httpx.ConnectError):
        return ProviderUnreachableError(
            provider=provider,
            endpoint=endpoint,
            details=str(exc),
        )
    if isinstance(exc, httpx.InvalidURL):
        return ModelDiscoveryError(
            "API 地址格式不正确",
            hint="地址需要以 http:// 或 https:// 开头，并包含正确的路径。",
            provider=provider,
            endpoint=endpoint,
            details=str(exc),
        )
    if isinstance(exc, httpx.HTTPError):
        return ProviderUnreachableError(
            provider=provider,
            endpoint=endpoint,
            details=str(exc),
        )
    # 非 HTTP 层的异常（例如传输实现内部报错）：细节只写日志，
    # 不放进响应体，避免把内部信息或凭据泄漏给前端。
    logger.warning("模型发现遇到未预期的异常: provider=%s endpoint=%s", provider, endpoint, exc_info=exc)
    return ModelDiscoveryError(
        provider=provider,
        endpoint=endpoint,
    )


# ----------------------------------------------------------------- 能力分类

_EMBEDDING_PATTERN = re.compile(
    r"embed|bge-|gte-|m3e|text-similarity|jina-embed|minilm|sentence-transformers|"
    r"nomic-embed|^e5-|/e5-|instructor-|text-embedding",
    re.I,
)
_RERANK_PATTERN = re.compile(r"rerank|bge-reranker|colbert", re.I)
_IMAGE_PATTERN = re.compile(
    r"dall-e|stable-diffusion|(^|[-_/])sd[-_]?\d|flux|midjourney|kolors|seedream|"
    r"image[-_ ]?gen|text-to-image|t2i|imagegen|imagen|cogview|wanx|\bvision-?gen\b",
    re.I,
)
_AUDIO_PATTERN = re.compile(r"whisper|tts|speech|audio|voice|sensevoice|cosyvoice|realtime", re.I)
_MODERATION_PATTERN = re.compile(r"moderation|guard|safety|omni-moderation", re.I)
_REASONING_PATTERN = re.compile(
    r"^o[134](-|$)|-o[134](-|$)|deepseek-r|deepseek-reasoner|qwq|reasoner|thinking|"
    r"magistral|reasoning|glm-z1|marco-o1|skywork-o",
    re.I,
)
_CODE_PATTERN = re.compile(r"codestral|codellama|codex|code-|-coder|codestral|qwen-coder|deepseek-coder", re.I)
_VISION_PATTERN = re.compile(
    r"gpt-4o|gpt-4-turbo|gpt-4\.1|gpt-4-vision|gpt-5|vision|llava|qwen-?vl|qwen2\.5-vl|"
    r"internvl|minicpm-v|pixtral|claude-3|claude-4|claude-sonnet|claude-opus|claude-haiku|"
    r"gemini|glm-4v|glm-4\.5v|step-1v|yi-vision|moonshot-v1-.*-vision|doubao-.*vision|o[134]-",
    re.I,
)
_CHAT_PATTERN = re.compile(
    r"gpt|claude|gemini|deepseek|qwen|glm|kimi|moonshot|llama|mistral|mixtral|command|"
    r"grok|ernie|hunyuan|doubao|minimax|step-|yi-|spark|baichuan|internlm|phi-|gemma|"
    r"nova-|sonar|jamba|hermes|wizardlm|openchat|vicuna|chatglm|o[134](-|$)|chat",
    re.I,
)


def classify_model(model_id: str) -> Sequence[Capability]:
    """根据模型 ID 的命名特征推断能力标签。

    这是启发式推断，只用于界面上的分组与过滤；用户始终可以手动输入模型名。

    判定顺序：

    1. 先收集「专属能力」标签（向量、重排、图像生成、语音、审核、推理、代码、视觉）；
    2. 若只命中向量/重排/图像生成/语音/审核，则认为是非对话模型，不加 ``chat``；
    3. 若命中推理/代码/视觉，则这些本身就是对话模型，补上 ``chat``；
    4. 若一个特征都没命中，按对话模型处理并标记 ``other``——OpenAI 兼容
       网关暴露的模型绝大多数都是对话模型，用户仍应能选中它。
    """

    if not model_id:
        return (Capability.OTHER,)

    caps: List[Capability] = []

    if _EMBEDDING_PATTERN.search(model_id):
        caps.append(Capability.EMBEDDING)
    if _RERANK_PATTERN.search(model_id):
        caps.append(Capability.RERANK)
    if _IMAGE_PATTERN.search(model_id):
        caps.append(Capability.IMAGE)
    if _AUDIO_PATTERN.search(model_id):
        caps.append(Capability.AUDIO)
    if _MODERATION_PATTERN.search(model_id):
        caps.append(Capability.MODERATION)
    if _REASONING_PATTERN.search(model_id):
        caps.append(Capability.REASONING)
    if _CODE_PATTERN.search(model_id):
        caps.append(Capability.CODE)
    if _VISION_PATTERN.search(model_id):
        caps.append(Capability.VISION)

    # 一个已知特征都没匹配上：按对话模型处理
    if not caps:
        return (Capability.CHAT, Capability.OTHER)

    # 非对话模型：仅命中向量 / 重排 / 图像生成 / 语音 / 审核
    non_chat_only = all(
        item in {
            Capability.EMBEDDING,
            Capability.RERANK,
            Capability.IMAGE,
            Capability.AUDIO,
            Capability.MODERATION,
        }
        for item in caps
    )

    if not non_chat_only:
        # 推理 / 代码 / 视觉类模型本身就是对话模型；
        # 其余情况则看命名是否像对话模型（gpt、claude、qwen…）。
        chat_implied = any(
            item in {Capability.REASONING, Capability.CODE, Capability.VISION} for item in caps
        )
        if chat_implied or _CHAT_PATTERN.search(model_id):
            caps.insert(0, Capability.CHAT)

    # 保序去重并限长
    ordered: List[Capability] = []
    for item in caps:
        if item not in ordered:
            ordered.append(item)
    return tuple(ordered[:MAX_CAPABILITIES_PER_MODEL])
