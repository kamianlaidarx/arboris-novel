# AIMETA P=Anthropic适配器|R=Claude模型列表获取|NR=不含缓存|E=AnthropicModelAdapter|X=internal|A=适配器|D=httpx|S=net|RD=./README.ai
"""Anthropic Claude 官方模型列表适配器。

Anthropic 已提供 ``GET /v1/models``，因此不再需要旧实现里那份会过期的
硬编码模型清单。认证使用 ``x-api-key`` 头，并要求 ``anthropic-version``。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..errors import ModelDiscoveryError
from .base import DiscoverContext, raise_for_status, wrap_request_error

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"


def derive_candidates(base_url: Optional[str]) -> List[str]:
    """推导 Anthropic 的模型列表端点。"""

    if not base_url or not base_url.strip():
        return ["https://api.anthropic.com/v1/models"]

    base = base_url.strip().rstrip("/")
    if base.endswith("#"):
        base = base[:-1].rstrip("/")
        return [base]
    if base.lower().endswith("/models"):
        return [base]
    if base.lower().endswith("/v1"):
        return [f"{base}/models"]
    return [f"{base}/v1/models", f"{base}/models"]


def parse_model_payload(payload: Any) -> List[Dict[str, Any]]:
    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        normalized.append(
            {
                "id": str(model_id),
                "description": entry.get("display_name"),
                "owned_by": "anthropic",
            }
        )
    return normalized


class AnthropicModelAdapter:
    """按 Anthropic 官方协议探测模型列表。"""

    provider_id = "anthropic"

    async def fetch(
        self,
        ctx: DiscoverContext,
    ) -> Tuple[Optional[str], List[Dict[str, Any]], List[str]]:
        candidates = derive_candidates(ctx.base_url)
        attempts: List[str] = []
        last_error: Optional[ModelDiscoveryError] = None

        for url in candidates:
            attempts.append(url)
            headers = {
                "x-api-key": ctx.api_key or "",
                "anthropic-version": ANTHROPIC_VERSION,
                "Accept": "application/json",
                **ctx.extra_headers,
            }
            try:
                async with ctx.client() as client:
                    response = await client.get(url, headers=headers)
            except Exception as exc:  # noqa: BLE001
                raise wrap_request_error(exc, provider=ctx.provider.id, endpoint=url) from exc

            try:
                raise_for_status(response, provider=ctx.provider.id, endpoint=url)
            except ModelDiscoveryError as exc:
                if exc.status_code == 404:
                    last_error = exc
                    continue
                raise

            try:
                entries = parse_model_payload(response.json())
            except Exception as exc:  # noqa: BLE001
                raise ModelDiscoveryError(
                    "模型列表响应不是合法 JSON",
                    provider=ctx.provider.id,
                    endpoint=url,
                    details=str(exc),
                ) from exc

            if entries:
                return url, entries, attempts

        if last_error is not None:
            last_error.attempted_endpoints = list(attempts)
            raise last_error
        return attempts[-1] if attempts else None, [], attempts
