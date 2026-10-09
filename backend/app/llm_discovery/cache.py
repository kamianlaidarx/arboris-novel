# AIMETA P=模型列表缓存|R=TTL缓存与并发去重|NR=不含网络请求|E=ModelListCache|X=internal|A=缓存类|D=asyncio|S=cache|RD=./README.ai
"""进程内模型列表 TTL 缓存。

两点设计考虑：

1. **按用户隔离**：模型列表依赖用户自己的 API Key，缓存键必须包含用户维度，
   否则会把 A 用户可见的模型泄露给 B 用户。
2. **并发去重**：同一个用户连点"获取模型"时只发一次上游请求，
   其余请求共享同一个 ``asyncio.Task`` 结果。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional, Tuple

from .models import ModelListResult

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    result: ModelListResult
    expires_at: float


def _copy_result(result: ModelListResult) -> ModelListResult:
    """拷贝一份结果，避免调用方修改缓存中的对象。"""

    return ModelListResult(
        provider=result.provider,
        provider_label=result.provider_label,
        base_url=result.base_url,
        endpoint=result.endpoint,
        models=list(result.models),
        warnings=list(result.warnings),
        attempts=list(result.attempts),
        elapsed_ms=result.elapsed_ms,
        cached=result.cached,
        expires_in=result.expires_in,
        truncated=result.truncated,
        limited=result.limited,
        total=result.total,
        latency_ms=result.latency_ms,
    )


class ModelListCache:
    """带容量上限的 TTL 缓存，并支持同一键的并发请求合并。"""

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 128) -> None:
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._inflight: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ key

    @staticmethod
    def build_key(
        *,
        user_id: Optional[int],
        provider: str,
        base_url: Optional[str],
        api_key: Optional[str],
        providers: Optional[Tuple[str, ...]] = None,
    ) -> str:
        """构造缓存键。

        API Key 只以摘要形式参与计算，绝不落盘、不打日志。
        """

        digest = hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:12]
        parts = [
            f"user={user_id if user_id is not None else 'anonymous'}",
            f"provider={provider}",
            f"base={base_url or ''}",
            f"key={digest}",
            f"providers={','.join(providers or ())}",
        ]
        return "|".join(parts)

    # ----------------------------------------------------------------- read

    async def get(self, key: str) -> Optional[ModelListResult]:
        if self.ttl_seconds <= 0:
            return None
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            remaining = entry.expires_at - time.monotonic()
            if remaining <= 0:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            cached = _copy_result(entry.result)
            # 重新计算剩余有效期，避免返回过期的 expires_in
            expires_in = int(remaining)
        cached.cached = True
        cached.expires_in = expires_in
        return cached

    async def set(self, key: str, result: ModelListResult) -> None:
        if self.ttl_seconds <= 0:
            return
        stored = _copy_result(result)
        stored.cached = False
        stored.expires_in = self.ttl_seconds
        async with self._lock:
            self._entries[key] = _Entry(
                result=stored,
                expires_at=time.monotonic() + self.ttl_seconds,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    async def invalidate(self, key_prefix: str) -> None:
        async with self._lock:
            for key in [item for item in self._entries if item.startswith(key_prefix)]:
                self._entries.pop(key, None)

    # ------------------------------------------------------------ coalesce

    async def get_or_create(
        self,
        key: str,
        factory: Callable[[], Awaitable[ModelListResult]],
    ) -> ModelListResult:
        """命中缓存直接返回；未命中时合并并发请求。"""

        cached = await self.get(key)
        if cached is not None:
            return cached

        async with self._lock:
            task = self._inflight.get(key)
            is_owner = task is None
            if task is None:
                task = asyncio.ensure_future(factory())
                self._inflight[key] = task

        try:
            result = await task
        finally:
            if is_owner:
                async with self._lock:
                    self._inflight.pop(key, None)

        if is_owner:
            await self.set(key, result)
            # 发起者拿到的是刚从上游发现的结果，标记为未命中缓存
            fresh = _copy_result(result)
            fresh.cached = False
            fresh.expires_in = self.ttl_seconds
            return fresh

        # 并发等待者拿到的是同一次发现的结果，对它们而言等同于命中缓存
        shared = _copy_result(result)
        shared.cached = True
        shared.expires_in = self.ttl_seconds
        return shared

    def clear(self) -> None:
        self._entries.clear()


_default_cache: Optional[ModelListCache] = None


def get_default_cache() -> ModelListCache:
    """进程级默认缓存实例，配置在首次调用时读取。"""

    global _default_cache
    if _default_cache is None:
        from ..core.config import settings

        _default_cache = ModelListCache(
            ttl_seconds=settings.llm_model_cache_ttl,
            max_entries=settings.llm_model_cache_max_entries,
        )
        logger.debug(
            "模型列表缓存初始化: ttl=%ss max_entries=%s",
            _default_cache.ttl_seconds,
            _default_cache.max_entries,
        )
    return _default_cache
