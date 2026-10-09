# AIMETA P=Ollama适配器|R=本地模型列表获取|NR=不含缓存|E=OllamaModelAdapter|X=internal|A=适配器|D=httpx|S=net|RD=./README.ai
"""Ollama 本地模型列表适配器（``GET /api/tags``）。

项目已经依赖 ollama 做嵌入模型，补上本地模型列表可以让"生成模型"与
"嵌入模型"的选择体验保持一致。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..errors import ModelDiscoveryError
from .base import DiscoverContext, raise_for_status, wrap_request_error

logger = logging.getLogger(__name__)


def derive_candidates(base_url: Optional[str]) -> List[str]:
    if not base_url or not base_url.strip():
        return ["http://localhost:11434/api/tags"]

    base = base_url.strip().rstrip("/")
    if base.endswith("#"):
        base = base[:-1].rstrip("/")
        return [base]
    if base.lower().endswith("/api/tags"):
        return [base]
    return [f"{base}/api/tags"]


def parse_model_payload(payload: Any) -> List[Dict[str, Any]]:
    entries = payload.get("models") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("model") or entry.get("name")
        if not name:
            continue
        details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
        size = entry.get("size")
        description_parts = [part for part in (details.get("family"), details.get("parameter_size")) if part]
        if isinstance(size, int) and size > 0:
            description_parts.append(f"{size / (1024 ** 3):.1f} GB")
        normalized.append(
            {
                "id": str(name),
                "owned_by": "ollama",
                "description": " · ".join(description_parts) or None,
            }
        )
    return normalized


class OllamaModelAdapter:
    """按 Ollama 原生 API 探测本地模型列表。"""

    provider_id = "ollama"

    async def fetch(
        self,
        ctx: DiscoverContext,
    ) -> Tuple[Optional[str], List[Dict[str, Any]], List[str]]:
        candidates = derive_candidates(ctx.base_url)
        attempts: List[str] = []
        last_error: Optional[ModelDiscoveryError] = None

        for url in candidates:
            attempts.append(url)
            headers = {"Accept": "application/json", **ctx.extra_headers}
            if ctx.api_key:
                headers["Authorization"] = f"Bearer {ctx.api_key}"

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
