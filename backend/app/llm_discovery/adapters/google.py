# AIMETA P=Google适配器|R=Gemini模型列表获取|NR=不含缓存|E=GoogleModelAdapter|X=internal|A=适配器|D=httpx|S=net|RD=./README.ai
"""Google Gemini 模型列表适配器。

相比旧实现的两点改进：

* API Key 通过 ``x-goog-api-key`` 头传递，不再拼进 URL（避免 Key 出现在
  日志与异常信息里）。
* 按 ``supportedGenerationMethods`` 过滤，只保留可对话/可生成的模型，
  并把 embedding 模型单独归类，而不是笼统返回一堆不可用的名字。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..errors import ModelDiscoveryError
from .base import DiscoverContext, raise_for_status, wrap_request_error

logger = logging.getLogger(__name__)


def derive_candidates(base_url: Optional[str]) -> List[str]:
    """推导 Gemini 的模型列表端点。"""

    if not base_url or not base_url.strip():
        return ["https://generativelanguage.googleapis.com/v1beta/models"]

    base = base_url.strip().rstrip("/")
    if base.endswith("#"):
        base = base[:-1].rstrip("/")
        return [base]
    if base.lower().endswith("/models"):
        return [base]
    if base.lower().endswith(("/v1beta", "/v1")):
        return [f"{base}/models"]
    return [f"{base}/v1beta/models", f"{base}/models"]


def parse_model_payload(payload: Any) -> List[Dict[str, Any]]:
    """解析 Gemini 的 ``models`` 响应。"""

    entries = payload.get("models") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or ""
        if not isinstance(name, str) or not name:
            continue
        if name.startswith("models/"):
            name = name[len("models/") :]

        methods = entry.get("supportedGenerationMethods") or []
        if not isinstance(methods, list):
            methods = []

        # 只保留能产出内容的模型；纯 embedding 模型仍保留但由能力分类识别
        if methods and not any(
            method in {"generateContent", "streamGenerateContent", "embedContent", "embedText"}
            for method in methods
        ):
            continue

        normalized.append(
            {
                "id": name,
                "owned_by": "google",
                "description": entry.get("displayName") or entry.get("description"),
            }
        )
    return normalized


class GoogleModelAdapter:
    """按 Google Generative Language API 探测模型列表。"""

    provider_id = "google"

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
                headers["x-goog-api-key"] = ctx.api_key

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
