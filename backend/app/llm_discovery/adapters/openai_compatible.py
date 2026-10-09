# AIMETA P=OpenAI兼容适配器|R=模型列表探测与解析|NR=不含缓存|E=OpenAICompatibleAdapter|X=internal|A=适配器|D=httpx|S=net|RD=./README.ai
"""OpenAI 兼容协议的模型列表适配器（主路径）。

覆盖范围：OpenAI 官方、DeepSeek、Moonshot、SiliconFlow、OpenRouter、Groq、
Mistral、xAI、阿里云百炼兼容模式，以及大量第三方中转站与自建网关。

这类服务的共同点是 ``GET {base}/v1/models``，但**路径前缀千差万别**：
有人填 ``https://host``，有人填 ``https://host/v1``，有人填
``https://host/api/paas/v4``。因此这里不猜一次，而是按优先级生成一小组
候选端点逐个探测，只要有一个返回模型列表就成功。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from ..errors import ModelDiscoveryError, NoModelListEndpointError
from .base import DiscoverContext, raise_for_status, wrap_request_error

logger = logging.getLogger(__name__)

# 候选端点数量上限，避免对同一个服务发太多无效请求
MAX_CANDIDATES = 4

_OPENAI_DEFAULT_ENDPOINT = "https://api.openai.com/v1/models"

_VERSION_SEGMENT = re.compile(r"^v\d+([a-z]+\d*)?$")
# 这些结尾段通常已经处于 API 根路径上，直接补 /models 即可
_ROOT_LIKE_SEGMENTS = {
    "openai",
    "api",
    "compatible-mode",
    "compatible_mode",
    "paas",
    "coding",
    "gateway",
    "proxy",
    "llm",
    "chat",
}


def derive_candidates(base_url: Optional[str]) -> List[str]:
    """从用户填写的 base_url 推导候选的模型列表端点。

    规则：

    1. 以 ``#`` 结尾：视为用户显式指定完整端点，原样使用、不做补全。
    2. 已经以 ``/models`` 结尾：直接使用。
    3. 末段是版本号（``v1``/``v4``/``v1beta``）：补 ``/models``，
       **不再**追加 ``/v1/models``，否则会拼出 ``/v1/v1/models`` 这种无效路径。
    4. 末段像 API 根路径（``/openai``、``/api``、``/compatible-mode``）：
       依次尝试 ``{base}/models`` 与 ``{base}/v1/models``。
    5. 其余（含裸域名）：依次尝试 ``/v1/models`` 与 ``/models``。
    """

    if not base_url or not base_url.strip():
        return [_OPENAI_DEFAULT_ENDPOINT]

    raw = base_url.strip()

    # 用户用 # 显式固定端点
    if raw.endswith("#"):
        pinned = raw[:-1].strip().rstrip("/")
        return [pinned or _OPENAI_DEFAULT_ENDPOINT]

    base = raw.rstrip("/")
    if base.lower().endswith("/models"):
        return [base]

    path = (urlsplit(base).path or "").lower().rstrip("/")
    last_segment = path.rsplit("/", 1)[-1] if path else ""

    if _VERSION_SEGMENT.match(last_segment):
        return [f"{base}/models"]

    if last_segment in _ROOT_LIKE_SEGMENTS:
        return _dedupe([f"{base}/models", f"{base}/v1/models"])[:MAX_CANDIDATES]

    return _dedupe([f"{base}/v1/models", f"{base}/models"])[:MAX_CANDIDATES]


def _dedupe(items: List[str]) -> List[str]:
    ordered: List[str] = []
    for item in items:
        if item not in ordered:
            ordered.append(item)
    return ordered


def parse_model_payload(payload: Any) -> List[Dict[str, Any]]:
    """解析 OpenAI 兼容的模型列表响应，兼容多种实际变体。"""

    entries: Any = None

    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        for key in ("data", "models", "result", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                entries = value
                break
            if isinstance(value, dict):
                inner = value.get("models") or value.get("data")
                if isinstance(inner, list):
                    entries = inner
                    break

    if not isinstance(entries, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            normalized.append({"id": entry})
            continue
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id") or entry.get("model") or entry.get("name")
        if not model_id or not isinstance(model_id, str):
            continue
        normalized.append(
            {
                "id": model_id,
                "owned_by": entry.get("owned_by") or entry.get("owner"),
                "created": entry.get("created") if isinstance(entry.get("created"), int) else None,
                "description": entry.get("description") or entry.get("display_name"),
            }
        )
    return normalized


class OpenAICompatibleAdapter:
    """按 OpenAI 兼容协议探测模型列表。"""

    provider_id = "openai-compatible"

    async def fetch(
        self,
        ctx: DiscoverContext,
    ) -> Tuple[Optional[str], List[Dict[str, Any]], List[str]]:
        candidates = derive_candidates(ctx.base_url)
        attempts: List[str] = []
        last_error: Optional[ModelDiscoveryError] = None
        empty_success: Optional[str] = None

        for url in candidates:
            attempts.append(url)
            try:
                entries = await self._request(ctx, url)
            except NoModelListEndpointError as exc:
                # 该候选路径不存在，换下一个候选
                last_error = exc
                logger.debug("候选端点无模型列表: url=%s", url)
                continue

            if entries:
                if len(attempts) > 1:
                    logger.info("模型列表探测成功: endpoint=%s attempts=%d", url, len(attempts))
                return url, entries, attempts

            # 200 但没有模型：记下来，继续尝试其它候选
            empty_success = url
            logger.debug("候选端点返回空模型列表: url=%s", url)

        if empty_success:
            raise ModelDiscoveryError(
                "该服务返回了空模型列表",
                hint="接口可访问但没有返回任何模型，请确认 API Key 的权限或手动输入模型名称。",
                provider=ctx.provider.id,
                endpoint=empty_success,
            )

        if last_error is not None:
            last_error.attempted_endpoints = list(attempts)
            raise last_error

        raise NoModelListEndpointError(
            provider=ctx.provider.id,
            endpoint=candidates[-1] if candidates else None,
            attempted_endpoints=list(attempts),
        )

    async def _request(self, ctx: DiscoverContext, url: str) -> List[Dict[str, Any]]:
        headers = {"Accept": "application/json", **ctx.extra_headers}
        if ctx.api_key:
            headers["Authorization"] = f"Bearer {ctx.api_key}"

        try:
            async with ctx.client() as client:
                response = await client.get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001 - 统一映射为分级异常
            raise wrap_request_error(exc, provider=ctx.provider.id, endpoint=url) from exc

        raise_for_status(response, provider=ctx.provider.id, endpoint=url)

        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise ModelDiscoveryError(
                "模型列表响应不是合法 JSON",
                hint="该地址可能不是 OpenAI 兼容接口，请确认 URL 是否填写正确。",
                provider=ctx.provider.id,
                endpoint=url,
                details=str(exc),
            ) from exc

        return parse_model_payload(payload)
