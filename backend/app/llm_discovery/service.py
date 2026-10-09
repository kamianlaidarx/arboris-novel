# AIMETA P=模型发现服务|R=供应商识别_适配器调度_缓存与过滤|NR=不含HTTP路由|E=ModelDiscoveryService|X=internal|A=服务类|D=httpx|S=net,cache|RD=./README.ai
"""模型发现编排服务。

职责：

1. 归一化并校验用户填写的 ``base_url``；
2. 按安全开关拦截内网地址；
3. 识别供应商协议族，选择对应适配器；
4. 调用适配器探测，把原始条目转换为带能力标签的 :class:`ModelInfo`；
5. 去重、排序、限流、按能力过滤；
6. 读写 TTL 缓存，并把过程中的告警一并返回。
"""

from __future__ import annotations

import logging
import time
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from ..core.config import settings
from .adapters import (
    AnthropicModelAdapter,
    DiscoverContext,
    GoogleModelAdapter,
    OllamaModelAdapter,
    OpenAICompatibleAdapter,
)
from .adapters.base import classify_model
from .cache import ModelListCache, get_default_cache
from .catalog import (
    ProviderDescriptor,
    ProviderKind,
    detect_provider,
    get_provider,
    is_local_or_private,
    normalize_base_url,
)
from .errors import (
    InvalidCredentialsError,
    InvalidProviderURLError,
    LocalEndpointBlockedError,
    NoModelListEndpointError,
)
from .models import Capability, ModelInfo, ModelListResult, dedupe_models

logger = logging.getLogger(__name__)

# 能力过滤的合法取值
_ALL_CAPABILITIES = {item.value for item in Capability}

_ADAPTERS = {
    ProviderKind.OPENAI_COMPATIBLE: OpenAICompatibleAdapter(),
    ProviderKind.ANTHROPIC: AnthropicModelAdapter(),
    ProviderKind.GOOGLE: GoogleModelAdapter(),
    ProviderKind.OLLAMA: OllamaModelAdapter(),
}


def _validate_base_url(base_url: str) -> None:
    parts = urlsplit(base_url.replace("#", ""))
    if parts.scheme not in {"http", "https"}:
        raise InvalidProviderURLError(details=f"unsupported scheme: {parts.scheme}")
    if not parts.netloc:
        raise InvalidProviderURLError(details="missing host")


class ModelDiscoveryService:
    """模型发现服务。

    构造参数全部可注入，便于在测试中替换传输层与缓存：

    >>> service = ModelDiscoveryService(transport=httpx.MockTransport(handler))
    """

    def __init__(
        self,
        *,
        cache: Optional[ModelListCache] = None,
        transport=None,
        timeout: Optional[float] = None,
        verify_tls: Optional[bool] = None,
        max_models: Optional[int] = None,
        allow_private_endpoints: Optional[bool] = None,
    ) -> None:
        self.cache = cache if cache is not None else get_default_cache()
        self.transport = transport
        self._timeout = timeout
        self._verify_tls = verify_tls
        self._max_models = max_models
        self._allow_private = allow_private_endpoints

    # ------------------------------------------------------------ 配置读取

    @property
    def timeout(self) -> float:
        return float(self._timeout if self._timeout is not None else settings.llm_model_request_timeout)

    @property
    def verify_tls(self) -> bool:
        return bool(self._verify_tls if self._verify_tls is not None else settings.llm_model_verify_tls)

    @property
    def max_models(self) -> int:
        return int(self._max_models if self._max_models is not None else settings.llm_model_max_results)

    @property
    def allow_private(self) -> bool:
        return bool(self._allow_private if self._allow_private is not None else settings.allow_private_llm_endpoints)

    # ---------------------------------------------------------------- 主流程

    async def discover(
        self,
        *,
        api_key: Optional[str],
        base_url: Optional[str] = None,
        provider_id: Optional[str] = None,
        user_id: Optional[int] = None,
        use_cache: bool = True,
        refresh: bool = False,
        capabilities: Optional[Sequence[str]] = None,
    ) -> ModelListResult:
        """发现模型列表。

        Args:
            api_key: 第三方 API Key；缺失时抛 :class:`InvalidCredentialsError`。
            base_url: 用户填写的服务地址；为空时使用供应商默认地址。
            provider_id: 显式指定供应商（跳过自动识别）。
            user_id: 缓存隔离维度。
            use_cache: 是否读写缓存。
            refresh: 为 ``True`` 时先失效缓存再重新探测。
            capabilities: 只保留包含指定能力标签的模型。
        """

        if not api_key or not api_key.strip():
            raise InvalidCredentialsError()

        descriptor = self._resolve_provider(base_url, provider_id)
        normalized = normalize_base_url(base_url) or descriptor.default_base_url

        if not normalized:
            raise InvalidProviderURLError(
                hint=f"{descriptor.label} 需要填写服务地址（Base URL）。",
                provider=descriptor.id,
            )

        _validate_base_url(normalized)

        if is_local_or_private(normalized) and not self.allow_private:
            raise LocalEndpointBlockedError(provider=descriptor.id, endpoint=normalized)

        cache_key = ModelListCache.build_key(
            user_id=user_id,
            provider=descriptor.id,
            base_url=normalized,
            api_key=api_key,
            providers=tuple(capabilities or ()),
        )

        if refresh and use_cache:
            await self.cache.invalidate(cache_key)

        if use_cache:
            result = await self.cache.get_or_create(
                cache_key,
                lambda: self._discover_uncached(
                    descriptor=descriptor,
                    base_url=normalized,
                    api_key=api_key,
                    user_id=user_id,
                ),
            )
        else:
            result = await self._discover_uncached(
                descriptor=descriptor,
                base_url=normalized,
                api_key=api_key,
                user_id=user_id,
            )

        if capabilities:
            result = self._apply_capability_filter(result, capabilities)

        return result

    # ------------------------------------------------------------ 内部实现

    def _resolve_provider(
        self,
        base_url: Optional[str],
        provider_id: Optional[str],
    ) -> ProviderDescriptor:
        """确定供应商：显式指定优先，其次按地址识别。"""

        if provider_id:
            explicit = get_provider(provider_id)
            if explicit is not None:
                return explicit
            logger.warning("未知的供应商标识 %s，回退到自动识别", provider_id)
        return detect_provider(base_url)

    async def _discover_uncached(
        self,
        *,
        descriptor: ProviderDescriptor,
        base_url: Optional[str],
        api_key: str,
        user_id: Optional[int],
    ) -> ModelListResult:
        adapter = _ADAPTERS.get(descriptor.kind)
        if adapter is None:
            # Azure 等没有标准列表接口的协议族：给出明确指引而不是假装成功
            raise NoModelListEndpointError(
                message=f"{descriptor.label} 不提供模型列表接口",
                hint=descriptor.notes or "请手动输入部署名称（Deployment Name）。",
                provider=descriptor.id,
                endpoint=base_url,
            )

        ctx = DiscoverContext(
            base_url=base_url,
            api_key=api_key,
            provider=descriptor,
            timeout=self.timeout,
            transport=self.transport,
            verify_tls=self.verify_tls,
        )

        started = time.perf_counter()
        endpoint, entries, attempts = await adapter.fetch(ctx)
        latency_ms = int((time.perf_counter() - started) * 1000)

        models = self._to_models(entries, descriptor)
        models, truncated = self._limit(models)

        result = ModelListResult(
            provider=descriptor.id,
            provider_label=descriptor.label,
            base_url=base_url,
            endpoint=endpoint,
            models=models,
            warnings=list(ctx.warnings),
            attempts=list(attempts),
            elapsed_ms=latency_ms,
            cached=False,
            expires_in=self.cache.ttl_seconds,
            truncated=truncated,
            total=len(models),
            latency_ms=latency_ms,
        )

        logger.info(
            "模型发现完成: provider=%s user_id=%s endpoint=%s models=%d attempts=%d latency=%dms",
            descriptor.id,
            user_id,
            endpoint,
            len(models),
            len(attempts),
            latency_ms,
        )
        return result

    @staticmethod
    def _to_models(entries: Iterable[dict], descriptor: ProviderDescriptor) -> List[ModelInfo]:
        models: List[ModelInfo] = []
        for entry in entries:
            model_id = str(entry.get("id", "")).strip()
            if not model_id:
                continue
            models.append(
                ModelInfo(
                    id=model_id,
                    owned_by=entry.get("owned_by") or descriptor.id,
                    created=entry.get("created") if isinstance(entry.get("created"), int) else None,
                    capabilities=classify_model(model_id),
                    description=entry.get("description"),
                )
            )
        return dedupe_models(models)

    def _limit(self, models: List[ModelInfo]) -> Tuple[List[ModelInfo], bool]:
        limit = self.max_models
        if limit > 0 and len(models) > limit:
            logger.warning("模型列表超过上限 %d，已截断（原 %d 条）", limit, len(models))
            return models[:limit], True
        return models, False

    @staticmethod
    def _apply_capability_filter(
        result: ModelListResult,
        capabilities: Sequence[str],
    ) -> ModelListResult:
        wanted = {item.strip().lower() for item in capabilities if item}
        wanted &= _ALL_CAPABILITIES
        if not wanted:
            return result

        filtered = [
            model
            for model in result.models
            if wanted.intersection(cap.value for cap in model.capabilities)
        ]
        result.models = filtered
        result.total = len(filtered)
        return result


async def discover_models(
    *,
    api_key: Optional[str],
    base_url: Optional[str] = None,
    provider_id: Optional[str] = None,
    user_id: Optional[int] = None,
    transport=None,
    **kwargs,
) -> ModelListResult:
    """便捷函数：一次性模型发现（测试与脚本入口）。"""

    service = ModelDiscoveryService(transport=transport)
    return await service.discover(
        api_key=api_key,
        base_url=base_url,
        provider_id=provider_id,
        user_id=user_id,
        **kwargs,
    )
