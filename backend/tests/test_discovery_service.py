# AIMETA P=模型发现集成测试|R=适配器探测_缓存_错误分级|NR=不含真实网络|E=test_discovery_service|X=internal|A=pytest|D=pytest,httpx|S=none|RD=./README.ai
"""使用 ``httpx.MockTransport`` 离线验证完整的模型发现流程。

这些测试覆盖的正是旧实现出问题的地方：把 URL 猜错、静默返回空列表、
没有缓存、错误信息丢失。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.llm_discovery.adapters.anthropic import AnthropicModelAdapter
from app.llm_discovery.adapters.base import DiscoverContext
from app.llm_discovery.cache import ModelListCache
from app.llm_discovery.catalog import get_provider
from app.llm_discovery.errors import (
    InvalidCredentialsError,
    InvalidProviderURLError,
    LocalEndpointBlockedError,
    NoModelListEndpointError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderUnreachableError,
)
from app.llm_discovery.models import Capability
from app.llm_discovery.service import ModelDiscoveryService

# --------------------------------------------------------------------- 辅助


class RecordingTransport(httpx.MockTransport):
    """记录所有请求的 MockTransport，便于断言端点与请求头。"""

    def __init__(self, handler):
        super().__init__(handler)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await super().handle_async_request(request)

    @property
    def urls(self) -> list[str]:
        return [str(item.url) for item in self.requests]


def make_service(handler, **kwargs) -> tuple[ModelDiscoveryService, RecordingTransport]:
    transport = RecordingTransport(handler)
    service = ModelDiscoveryService(
        transport=transport,
        cache=kwargs.pop("cache", ModelListCache(ttl_seconds=0)),
        **kwargs,
    )
    return service, transport


def ok_models(*model_ids: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [{"id": model_id, "owned_by": "test"} for model_id in model_ids],
        },
    )


# ----------------------------------------------------------------- 成功路径


async def test_discovers_models_from_v1_endpoint():
    """标准 https://host/v1 场景应命中 /v1/models。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return ok_models("deepseek-chat", "deepseek-reasoner", "text-embedding-3-large")
        return httpx.Response(404, json={"error": {"message": "not found"}})

    service, transport = make_service(handler)
    result = await service.discover(api_key="sk-test", base_url="https://api.deepseek.com/v1")

    assert result.provider == "deepseek"
    assert result.endpoint == "https://api.deepseek.com/v1/models"
    assert "deepseek-chat" in result.model_ids()
    assert result.attempts == ["https://api.deepseek.com/v1/models"]
    assert result.latency_ms is not None


async def test_falls_back_across_candidate_endpoints():
    """只挂 /models 的自建网关，在用户填写裸域名时也应被探测到。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/models":
            return ok_models("my-local-model")
        return httpx.Response(404, json={"error": {"message": "no such route"}})

    service, transport = make_service(handler)
    result = await service.discover(api_key="sk-test", base_url="https://gateway.example.com")

    # 先试了标准 /v1/models（404），再试 /models（成功）
    assert transport.urls == [
        "https://gateway.example.com/v1/models",
        "https://gateway.example.com/models",
    ]
    assert result.endpoint == "https://gateway.example.com/models"
    assert result.model_ids() == ["my-local-model"]


async def test_sends_bearer_token_and_never_leaks_key_in_result():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return ok_models("gpt-4o-mini")

    service, _ = make_service(handler)
    result = await service.discover(api_key="sk-super-secret", base_url="https://api.openai.com/v1")

    assert captured["auth"] == "Bearer sk-super-secret"
    # 结果里不应包含 Key
    assert "sk-super-secret" not in json.dumps(result.__dict__, default=str)


async def test_custom_endpoint_via_hash_suffix():
    """以 # 结尾表示用户显式指定端点，不应再做任何路径补全。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/custom/list":
            return ok_models("custom-model")
        return httpx.Response(404)

    service, transport = make_service(handler)
    result = await service.discover(api_key="k", base_url="https://host/custom/list#")

    assert transport.urls == ["https://host/custom/list"]
    assert result.model_ids() == ["custom-model"]


# --------------------------------------------------------------- 错误分级


async def test_auth_error_is_surfaced_not_swallowed():
    service, _ = make_service(lambda request: httpx.Response(401, json={"error": {"message": "bad key"}}))

    with pytest.raises(ProviderAuthError) as excinfo:
        await service.discover(api_key="sk-bad", base_url="https://api.openai.com/v1")

    payload = excinfo.value.to_dict()
    assert payload["message"]
    assert payload["hint"]
    assert payload["upstream_status"] == 401
    assert excinfo.value.http_status == 401


async def test_rate_limit_maps_to_429():
    service, _ = make_service(lambda request: httpx.Response(429, json={"error": {"message": "slow down"}}))

    with pytest.raises(ProviderRateLimitError) as excinfo:
        await service.discover(api_key="k", base_url="https://api.openai.com/v1")

    assert excinfo.value.http_status == 429


async def test_server_error_maps_to_502():
    service, _ = make_service(lambda request: httpx.Response(503, text="upstream down"))

    with pytest.raises(ProviderServerError) as excinfo:
        await service.discover(api_key="k", base_url="https://api.openai.com/v1")

    assert excinfo.value.http_status == 502
    assert "upstream down" in (excinfo.value.details or "")


async def test_all_candidates_404_reports_no_endpoint_with_attempts():
    """中转站完全不支持 /models 时，必须明确告知而不是返回空列表。"""

    service, transport = make_service(lambda request: httpx.Response(404, json={"error": {"message": "nope"}}))

    with pytest.raises(NoModelListEndpointError) as excinfo:
        await service.discover(api_key="k", base_url="https://relay.example.com")

    payload = excinfo.value.to_dict()
    assert payload["message"]
    assert payload["attempted_endpoints"]
    # 裸域名会依次尝试 /v1/models 与 /models
    assert len(payload["attempted_endpoints"]) == len(transport.urls) == 2
    assert excinfo.value.http_status == 404
    # 提示应引导用户手动输入模型名
    assert "手动输入" in payload["hint"]


async def test_connection_error_maps_to_504():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure", request=request)

    service, _ = make_service(handler)

    with pytest.raises(ProviderUnreachableError) as excinfo:
        await service.discover(api_key="k", base_url="https://nonexistent.invalid/v1")

    assert excinfo.value.http_status == 504


async def test_timeout_maps_to_504():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    service, _ = make_service(handler)

    with pytest.raises(ProviderUnreachableError) as excinfo:
        await service.discover(api_key="k", base_url="https://slow.example.com/v1")

    assert excinfo.value.http_status == 504


async def test_empty_model_list_is_reported():
    from app.llm_discovery.errors import ModelDiscoveryError

    service, _ = make_service(lambda request: httpx.Response(200, json={"data": []}))

    with pytest.raises(ModelDiscoveryError) as excinfo:
        await service.discover(api_key="k", base_url="https://api.openai.com/v1")

    assert "空" in excinfo.value.message


async def test_missing_api_key_raises_invalid_credentials():
    service, transport = make_service(lambda request: ok_models("x"))

    with pytest.raises(InvalidCredentialsError):
        await service.discover(api_key="   ", base_url="https://api.openai.com/v1")

    assert transport.requests == []


async def test_private_endpoint_blocked_by_default():
    service, transport = make_service(lambda request: ok_models("x"))

    with pytest.raises(LocalEndpointBlockedError):
        await service.discover(api_key="k", base_url="http://127.0.0.1:11434")

    assert transport.requests == []


async def test_private_endpoint_allowed_when_enabled():
    service, _ = make_service(
        lambda request: httpx.Response(200, json={"models": [{"model": "llama3:8b"}]}),
        allow_private_endpoints=True,
    )
    result = await service.discover(api_key="k", base_url="http://127.0.0.1:11434")

    assert result.provider == "ollama"
    assert result.model_ids() == ["llama3:8b"]


async def test_invalid_scheme_is_rejected():
    service, _ = make_service(lambda request: ok_models("x"))

    with pytest.raises(InvalidProviderURLError):
        await service.discover(api_key="k", base_url="ftp://example.com/v1")


# ------------------------------------------------------------------- 缓存


async def test_cache_hit_avoids_second_upstream_call():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return ok_models("cached-model")

    transport = RecordingTransport(handler)
    service = ModelDiscoveryService(transport=transport, cache=ModelListCache(ttl_seconds=300))

    first = await service.discover(api_key="k", base_url="https://api.openai.com/v1", user_id=1)
    second = await service.discover(api_key="k", base_url="https://api.openai.com/v1", user_id=1)

    assert calls["count"] == 1
    assert first.cached is False
    assert second.cached is True
    assert second.expires_in > 0
    assert second.model_ids() == ["cached-model"]


async def test_refresh_bypasses_cache():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return ok_models("m")

    service = ModelDiscoveryService(
        transport=RecordingTransport(handler),
        cache=ModelListCache(ttl_seconds=300),
    )

    await service.discover(api_key="k", base_url="https://api.openai.com/v1", user_id=1)
    refreshed = await service.discover(
        api_key="k", base_url="https://api.openai.com/v1", user_id=1, refresh=True
    )

    assert calls["count"] == 2
    assert refreshed.cached is False


async def test_cache_is_isolated_per_user():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return ok_models("m")

    service = ModelDiscoveryService(
        transport=RecordingTransport(handler),
        cache=ModelListCache(ttl_seconds=300),
    )

    await service.discover(api_key="key-a", base_url="https://api.openai.com/v1", user_id=1)
    await service.discover(api_key="key-b", base_url="https://api.openai.com/v1", user_id=2)

    # 不同用户/不同 Key 不应共享缓存
    assert calls["count"] == 2


async def test_cache_disabled_when_ttl_zero():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return ok_models("m")

    service = ModelDiscoveryService(
        transport=RecordingTransport(handler),
        cache=ModelListCache(ttl_seconds=0),
    )

    await service.discover(api_key="k", base_url="https://api.openai.com/v1", user_id=1)
    await service.discover(api_key="k", base_url="https://api.openai.com/v1", user_id=1)

    assert calls["count"] == 2


async def test_concurrent_requests_are_coalesced():
    calls = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        await asyncio.sleep(0.05)
        return ok_models("shared-model")

    service = ModelDiscoveryService(
        transport=httpx.MockTransport(handler),
        cache=ModelListCache(ttl_seconds=300),
    )

    results = await asyncio.gather(
        *[
            service.discover(api_key="k", base_url="https://api.openai.com/v1", user_id=7)
            for _ in range(5)
        ]
    )

    assert calls["count"] == 1
    assert all(item.model_ids() == ["shared-model"] for item in results)


async def test_cache_key_does_not_contain_raw_api_key():
    key = ModelListCache.build_key(
        user_id=1,
        provider="openai",
        base_url="https://api.openai.com/v1",
        api_key="sk-plaintext-secret",
    )
    assert "sk-plaintext-secret" not in key


# --------------------------------------------------------------- 能力过滤


async def test_capability_filter_keeps_only_matching_models():
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_models("gpt-4o-mini", "text-embedding-3-large", "dall-e-3")

    service, _ = make_service(handler)
    result = await service.discover(
        api_key="k",
        base_url="https://api.openai.com/v1",
        capabilities=["embedding"],
    )

    assert result.model_ids() == ["text-embedding-3-large"]
    assert result.total == 1


async def test_capability_counts_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_models("gpt-4o-mini", "text-embedding-3-large")

    service, _ = make_service(handler)
    result = await service.discover(api_key="k", base_url="https://api.openai.com/v1")

    counts = result.capability_counts()
    assert counts["chat"] == 1
    assert counts["embedding"] == 1


# --------------------------------------------------------------- 数量上限


async def test_max_models_truncates_and_flags():
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_models(*[f"model-{index:03d}" for index in range(50)])

    service, _ = make_service(handler, max_models=10)
    result = await service.discover(api_key="k", base_url="https://api.openai.com/v1")

    assert len(result.model_ids()) == 10
    assert result.truncated is True


# ----------------------------------------------------- 显式供应商 / 预设


async def test_explicit_provider_overrides_detection():
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_models("m")

    service, transport = make_service(handler)
    result = await service.discover(
        api_key="k",
        base_url="https://my-relay.example.com/v1",
        provider_id="siliconflow",
    )

    assert result.provider == "siliconflow"
    assert result.endpoint == "https://my-relay.example.com/v1/models"


async def test_provider_presets_cover_expected_ids():
    from app.services.llm_config_service import LLMConfigService

    presets = LLMConfigService.list_provider_presets()
    ids = {item.id for item in presets}

    assert {"openai", "deepseek", "siliconflow", "openrouter", "ollama"} <= ids

    azure = next(item for item in presets if item.id == "azure-openai")
    assert azure.supports_model_list is False
    # 不支持列表的供应商必须给出说明
    assert azure.notes


# ------------------------------------------------------- 其他协议适配器


async def test_anthropic_adapter_uses_api_key_header():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["x-api-key"] = request.headers.get("x-api-key", "")
        captured["version"] = request.headers.get("anthropic-version", "")
        return httpx.Response(
            200,
            json={"data": [{"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5"}]},
        )

    adapter = AnthropicModelAdapter()
    transport = RecordingTransport(handler)
    ctx = DiscoverContext(
        base_url="https://api.anthropic.com/v1",
        api_key="sk-ant-test",
        provider=get_provider("anthropic"),
        transport=transport,
    )

    endpoint, entries, _ = await adapter.fetch(ctx)

    assert endpoint == "https://api.anthropic.com/v1/models"
    assert captured["x-api-key"] == "sk-ant-test"
    assert captured["version"] == "2023-06-01"
    assert entries[0]["id"] == "claude-sonnet-4-5"


async def test_google_adapter_filters_by_generation_methods():
    def handler(request: httpx.Request) -> httpx.Response:
        # Key 必须在请求头而不是 URL 里
        assert "key=" not in str(request.url)
        assert request.headers.get("x-goog-api-key") == "gk-test"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-2.0-flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                    {
                        "name": "models/some-internal-thing",
                        "supportedGenerationMethods": ["countTokens"],
                    },
                ]
            },
        )

    service, _ = make_service(handler)
    result = await service.discover(api_key="gk-test", base_url="https://generativelanguage.googleapis.com/v1beta")

    assert result.provider == "google"
    assert "gemini-2.0-flash" in result.model_ids()
    assert "embedding-001" in result.model_ids()
    # 既不生成也不嵌入的模型被过滤掉
    assert "some-internal-thing" not in result.model_ids()


async def test_azure_returns_actionable_error():
    service, _ = make_service(lambda request: ok_models("x"))

    with pytest.raises(NoModelListEndpointError) as excinfo:
        await service.discover(api_key="k", base_url="https://foo.openai.azure.com")

    assert "Azure" in excinfo.value.message or "部署" in (excinfo.value.hint or "")


async def test_unknown_provider_id_falls_back_to_detection():
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_models("m")

    service, _ = make_service(handler)
    result = await service.discover(
        api_key="k",
        base_url="https://api.deepseek.com/v1",
        provider_id="does-not-exist",
    )

    assert result.provider == "deepseek"


async def test_capabilities_are_attached_to_models():
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_models("deepseek-reasoner", "text-embedding-3-large")

    service, _ = make_service(handler)
    result = await service.discover(api_key="k", base_url="https://api.deepseek.com/v1")

    by_id = {model.id: model for model in result.models}
    assert Capability.REASONING in by_id["deepseek-reasoner"].capabilities
    assert Capability.EMBEDDING in by_id["text-embedding-3-large"].capabilities
