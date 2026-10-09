# AIMETA P=LLM配置API测试|R=路由契约_错误映射_配置回退|NR=不含真实数据库|E=test_llm_config_api|X=internal|A=pytest|D=pytest,fastapi|S=none|RD=./README.ai
"""LLM 配置路由层测试。

用依赖覆盖把数据库与会话完全替换掉，只验证 HTTP 契约：
状态码、响应结构、以及"请求未带 Key 时回退到已保存配置"的行为。

注意：这里使用 ``httpx.ASGITransport`` 而不是 ``fastapi.testclient.TestClient``，
因为项目锁定的 ``starlette 0.36`` 与 ``httpx 0.28`` 组合下 TestClient 不可用
（starlette 会向 httpx.Client 传入已被移除的 ``app=`` 参数）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import httpx
import pytest
from fastapi import FastAPI

from app.api.routers import llm_config as llm_config_router
from app.core.dependencies import get_current_user
from app.llm_discovery.cache import ModelListCache
from app.llm_discovery.service import ModelDiscoveryService
from app.schemas.user import UserInDB
from app.services.llm_config_service import LLMConfigService

FAKE_USER = UserInDB(
    id=42,
    username="tester",
    email="tester@example.com",
    hashed_password="x",
    is_admin=False,
    is_active=True,
)


class _StoredConfig:
    """模拟已保存的 LLM 配置行。"""

    def __init__(self, url: Optional[str], key: Optional[str], model: Optional[str] = None):
        self.llm_provider_url = url
        self.llm_provider_api_key = key
        self.llm_provider_model = model


@asynccontextmanager
async def api_client(
    handler,
    *,
    stored: Optional[_StoredConfig] = None,
    cache: Optional[ModelListCache] = None,
):
    """构造一个绕过数据库的测试客户端。"""

    app = FastAPI()
    app.include_router(llm_config_router.router)

    discovery = ModelDiscoveryService(
        transport=httpx.MockTransport(handler),
        cache=cache if cache is not None else ModelListCache(ttl_seconds=0),
    )
    service = LLMConfigService(session=None, discovery=discovery)  # type: ignore[arg-type]

    async def _get_stored(user_id: int):
        return stored

    # 只替换仓库读取，避免依赖真实数据库
    service.repo.get_by_user = _get_stored  # type: ignore[method-assign]

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[llm_config_router.get_llm_config_service] = lambda: service

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def ok_models(*model_ids: str) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": item, "owned_by": "test"} for item in model_ids]})


# ------------------------------------------------------------------ 成功路径


async def test_list_models_returns_structured_payload():
    async with api_client(lambda request: ok_models("gpt-4o-mini", "text-embedding-3-large")) as client:
        response = await client.post(
            "/api/llm-config/models",
            json={"llm_provider_api_key": "sk-test", "llm_provider_url": "https://api.openai.com/v1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai"
    assert body["provider_label"] == "OpenAI"
    assert body["endpoint"] == "https://api.openai.com/v1/models"
    # 既提供结构化 models，也提供扁平 model_ids
    assert body["model_ids"] == ["gpt-4o-mini", "text-embedding-3-large"]
    assert body["models"][0]["id"] == "gpt-4o-mini"
    assert "chat" in body["models"][0]["capabilities"]
    assert body["capability_counts"]["embedding"] == 1
    assert body["cached"] is False


async def test_list_models_falls_back_to_stored_config():
    """保存配置后再次点击刷新，无需重复粘贴 Key。"""

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return ok_models("deepseek-chat")

    async with api_client(
        handler,
        stored=_StoredConfig("https://api.deepseek.com/v1", "sk-stored-key"),
    ) as client:
        response = await client.post("/api/llm-config/models", json={})

    assert response.status_code == 200
    assert response.json()["provider"] == "deepseek"
    assert seen["auth"] == "Bearer sk-stored-key"


async def test_list_models_normalizes_bare_hostname():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return ok_models("m")

    async with api_client(handler) as client:
        response = await client.post(
            "/api/llm-config/models",
            json={"llm_provider_api_key": "k", "llm_provider_url": "api.siliconflow.cn/v1"},
        )

    assert response.status_code == 200
    # 缺少协议时自动补 https
    assert seen["url"] == "https://api.siliconflow.cn/v1/models"


async def test_capability_filter_is_applied():
    async with api_client(lambda request: ok_models("gpt-4o-mini", "text-embedding-3-large")) as client:
        response = await client.post(
            "/api/llm-config/models",
            json={
                "llm_provider_api_key": "k",
                "llm_provider_url": "https://api.openai.com/v1",
                "capabilities": ["embedding"],
            },
        )

    assert response.status_code == 200
    assert response.json()["model_ids"] == ["text-embedding-3-large"]


async def test_provider_presets_endpoint():
    async with api_client(lambda request: ok_models("m")) as client:
        response = await client.get("/api/llm-config/providers")

    assert response.status_code == 200
    presets = {item["id"]: item for item in response.json()}
    assert "deepseek" in presets
    assert presets["deepseek"]["default_base_url"] == "https://api.deepseek.com/v1"


async def test_describe_provider_endpoint():
    async with api_client(lambda request: ok_models("m")) as client:
        response = await client.get(
            "/api/llm-config/provider",
            params={"base_url": "https://openrouter.ai/api/v1"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == "openrouter"


# ------------------------------------------------------------------ 错误映射


@pytest.mark.parametrize(
    "upstream_status,expected_status,expected_error",
    [
        (401, 401, "ProviderAuthError"),
        (403, 401, "ProviderAuthError"),
        (429, 429, "ProviderRateLimitError"),
        (404, 404, "NoModelListEndpointError"),
        (500, 502, "ProviderServerError"),
    ],
)
async def test_upstream_errors_map_to_structured_detail(upstream_status, expected_status, expected_error):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"error": {"message": "upstream says no"}})

    async with api_client(handler) as client:
        response = await client.post(
            "/api/llm-config/models",
            json={"llm_provider_api_key": "k", "llm_provider_url": "https://api.openai.com/v1"},
        )

    assert response.status_code == expected_status
    detail = response.json()["detail"]
    assert detail["error"] == expected_error
    # 关键：必须给出可读原因与排查建议，而不是空列表
    assert detail["message"]
    assert detail["hint"]
    assert detail["upstream_status"] == upstream_status


async def test_missing_key_returns_400_with_hint():
    async with api_client(lambda request: ok_models("m")) as client:
        response = await client.post("/api/llm-config/models", json={})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "InvalidCredentialsError"
    assert "API Key" in detail["message"]


async def test_no_model_endpoint_lists_attempted_endpoints():
    async with api_client(lambda request: httpx.Response(404, json={"error": {"message": "nope"}})) as client:
        response = await client.post(
            "/api/llm-config/models",
            json={"llm_provider_api_key": "k", "llm_provider_url": "https://relay.example.com"},
        )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["attempted_endpoints"] == [
        "https://relay.example.com/v1/models",
        "https://relay.example.com/models",
    ]


async def test_private_endpoint_blocked_with_actionable_hint():
    async with api_client(lambda request: ok_models("m")) as client:
        response = await client.post(
            "/api/llm-config/models",
            json={"llm_provider_api_key": "k", "llm_provider_url": "http://192.168.1.10:8000/v1"},
        )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == "LocalEndpointBlockedError"
    assert "ALLOW_PRIVATE_LLM_ENDPOINTS" in detail["hint"]


async def test_unexpected_error_is_not_leaked_to_client():
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom with secret sk-leak")

    async with api_client(handler) as client:
        response = await client.post(
            "/api/llm-config/models",
            json={"llm_provider_api_key": "k", "llm_provider_url": "https://api.openai.com/v1"},
        )

    # 未预期的内部异常被兜底捕获并翻译成结构化错误，而不是 500 堆栈
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["message"]
    assert detail["hint"]
    # 内部异常原文（可能含敏感信息）绝不出现在响应里
    assert "sk-leak" not in response.text
    assert "details" not in detail


# -------------------------------------------------------------------- 缓存


async def test_second_call_is_served_from_cache():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return ok_models("cached-model")

    payload = {"llm_provider_api_key": "k", "llm_provider_url": "https://api.openai.com/v1"}
    async with api_client(handler, cache=ModelListCache(ttl_seconds=300)) as client:
        first = await client.post("/api/llm-config/models", json=payload)
        second = await client.post("/api/llm-config/models", json=payload)

    assert calls["count"] == 1
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["expires_in"] > 0


async def test_refresh_flag_bypasses_cache():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return ok_models("m")

    payload = {"llm_provider_api_key": "k", "llm_provider_url": "https://api.openai.com/v1"}
    async with api_client(handler, cache=ModelListCache(ttl_seconds=300)) as client:
        await client.post("/api/llm-config/models", json=payload)
        await client.post("/api/llm-config/models", json={**payload, "refresh": True})

    assert calls["count"] == 2
