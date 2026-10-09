# AIMETA P=LLM配置服务_模型配置与模型发现编排|R=配置管理_模型发现|NR=不含模型调用|E=LLMConfigService|X=internal|A=服务类|D=sqlalchemy|S=db,net|RD=./README.ai
"""用户自定义 LLM 配置服务。

重构要点（对比旧实现）：

* 删除了 ``_identify_provider`` 的 URL 关键字猜测，供应商识别统一交给
  :mod:`app.llm_discovery.catalog` 的规则表；
* 删除了 Anthropic / Azure / Cohere 的硬编码模型清单，改为真实探测；
  确实没有列表接口的服务会返回明确的错误提示，而不是伪造一份清单；
* 模型列表获取支持缓存、并发合并、能力过滤与结构化错误。
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm_discovery import ModelDiscoveryService, ModelListResult
from ..llm_discovery.catalog import detect_provider, get_provider, list_providers, normalize_base_url
from ..models import LLMConfig
from ..repositories.llm_config_repository import LLMConfigRepository
from ..schemas.llm_config import (
    LLMConfigCreate,
    LLMConfigRead,
    ModelInfoRead,
    ModelListResponse,
    ProviderInfoRead,
)

logger = logging.getLogger(__name__)


class LLMConfigService:
    """用户自定义 LLM 配置服务。"""

    def __init__(self, session: AsyncSession, *, discovery: Optional[ModelDiscoveryService] = None):
        self.session = session
        self.repo = LLMConfigRepository(session)
        self._discovery = discovery

    # ------------------------------------------------------------------ 属性

    @property
    def discovery(self) -> ModelDiscoveryService:
        """按需创建发现服务，便于测试注入。"""

        if self._discovery is None:
            self._discovery = ModelDiscoveryService()
        return self._discovery

    # ------------------------------------------------------------------ CRUD

    async def upsert_config(self, user_id: int, payload: LLMConfigCreate) -> LLMConfigRead:
        instance = await self.repo.get_by_user(user_id)
        data = payload.model_dump(exclude_unset=True)
        if instance:
            await self.repo.update_fields(instance, **data)
        else:
            instance = LLMConfig(user_id=user_id, **data)
            await self.repo.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)
        return LLMConfigRead.model_validate(instance)

    async def get_config(self, user_id: int) -> Optional[LLMConfigRead]:
        instance = await self.repo.get_by_user(user_id)
        return LLMConfigRead.model_validate(instance) if instance else None

    async def delete_config(self, user_id: int) -> bool:
        instance = await self.repo.get_by_user(user_id)
        if not instance:
            return False
        await self.repo.delete(instance)
        await self.session.commit()
        # 配置被删除后，其模型列表缓存也不应继续生效
        await self.discovery.cache.invalidate(f"user={user_id}|")
        return True

    # -------------------------------------------------------------- 模型发现

    async def discover_models(
        self,
        *,
        user_id: Optional[int],
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: Optional[str] = None,
        refresh: bool = False,
        capabilities: Optional[Sequence[str]] = None,
    ) -> ModelListResult:
        """发现模型列表。

        当请求未携带 API Key / 地址时，回退到该用户已保存的配置，
        这样"保存后再刷新"不需要用户重复粘贴 Key。
        """

        resolved_key = api_key
        resolved_url = base_url
        resolved_provider = provider

        if not resolved_key or (not resolved_url and not resolved_provider):
            stored = await self.repo.get_by_user(user_id) if user_id else None
            if stored:
                if not resolved_key:
                    resolved_key = stored.llm_provider_api_key
                if not resolved_url:
                    resolved_url = stored.llm_provider_url

        return await self.discovery.discover(
            api_key=resolved_key,
            base_url=resolved_url,
            provider_id=resolved_provider,
            user_id=user_id,
            refresh=refresh,
            capabilities=capabilities,
        )

    @staticmethod
    def to_response(result: ModelListResult) -> ModelListResponse:
        """把发现结果转换为 API 响应模型。"""

        return ModelListResponse(
            provider=result.provider,
            provider_label=result.provider_label,
            base_url=result.base_url,
            endpoint=result.endpoint,
            models=[
                ModelInfoRead(
                    id=model.id,
                    capabilities=[cap.value for cap in model.capabilities],
                    owned_by=model.owned_by,
                    created=model.created,
                    description=model.description,
                )
                for model in result.models
            ],
            model_ids=result.model_ids(),
            total=result.total or len(result.models),
            cached=result.cached,
            expires_in=result.expires_in,
            truncated=result.truncated,
            elapsed_ms=result.elapsed_ms,
            latency_ms=result.latency_ms,
            attempts=result.attempts,
            warnings=result.warnings,
            capability_counts=result.capability_counts(),
        )

    # ------------------------------------------------------------ 供应商预设

    @staticmethod
    def list_provider_presets() -> List[ProviderInfoRead]:
        """返回前端可用的供应商预设。

        ``supports_model_list`` 为 ``False`` 的供应商（Azure、智谱等）说明其
        协议族没有标准的模型列表接口，界面上会提示用户手动输入模型名。
        """

        # 这些协议族目前没有通用列表接口
        unsupported = {"azure-openai"}

        presets: List[ProviderInfoRead] = []
        for descriptor in list_providers():
            presets.append(
                ProviderInfoRead(
                    id=descriptor.id,
                    label=descriptor.label,
                    kind=descriptor.kind.value,
                    default_base_url=descriptor.default_base_url,
                    docs_url=descriptor.docs_url,
                    notes=descriptor.notes,
                    supports_model_list=descriptor.id not in unsupported,
                )
            )
        return presets

    @staticmethod
    def describe_provider(base_url: Optional[str], provider: Optional[str] = None) -> ProviderInfoRead:
        """描述当前地址对应的供应商（用于前端展示"已识别为 …"）。"""

        descriptor = get_provider(provider) if provider else None
        if descriptor is None:
            descriptor = detect_provider(base_url)
        return ProviderInfoRead(
            id=descriptor.id,
            label=descriptor.label,
            kind=descriptor.kind.value,
            default_base_url=descriptor.default_base_url,
            docs_url=descriptor.docs_url,
            notes=descriptor.notes,
            supports_model_list=descriptor.id != "azure-openai",
        )

    # ------------------------------------------------------------------ 兼容

    async def get_available_models(
        self,
        api_key: str,
        base_url: Optional[str] = None,
    ) -> List[str]:
        """兼容旧签名的薄封装：只返回模型名列表。

        新代码请直接使用 :meth:`discover_models`，它可以拿到能力标签、
        命中端点与结构化错误。
        """

        result = await self.discovery.discover(api_key=api_key, base_url=base_url)
        return result.model_ids()

    @staticmethod
    def normalize_url(value: Optional[str]) -> Optional[str]:
        return normalize_base_url(value)


__all__ = ["LLMConfigService"]
