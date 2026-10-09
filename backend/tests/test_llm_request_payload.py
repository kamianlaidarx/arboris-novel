"""LLM 请求构造的回归测试。

背景：``timeout`` 曾被放进请求体（payload）而不是作为 SDK 调用参数传入。
后果有两个：
  1. 它被序列化成请求体里的非法字段发给上游；
  2. 超时**完全不生效**——SDK 只认 ``create(timeout=...)``。

表现是上游卡住时请求一直挂着，直到被 Cloudflare(100s) 掐断，
用户看到「AI 服务内部错误」或 524，而日志里看不出是超时问题。
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.utils.llm_tool import ChatMessage, LLMClient


class _FakeCompletions:
    def __init__(self) -> None:
        self.captured: Dict[str, Any] = {}

    async def create(self, **kwargs: Any):
        self.captured = kwargs

        async def _gen():
            class _Delta:
                content = "ok"
            class _Choice:
                delta = _Delta()
                finish_reason = "stop"
            class _Chunk:
                choices = [_Choice()]
            yield _Chunk()

        return _gen()


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()
        self.chat = _FakeChat(self.completions)


async def _collect(client: LLMClient, messages: List[ChatMessage], **kw):
    out = []
    async for part in client.stream_chat(messages, **kw):
        out.append(part)
    return out


@pytest.fixture
def client(monkeypatch):
    # 构造 AsyncOpenAI 时会读取环境里的代理变量。本机环境含
    # ALL_PROXY=socks5 与带方括号的 no_proxy（httpx 解析不了），
    # 会与本次测试无关地报错，所以这里先清掉。
    for var in (
        "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
        "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy",
    ):
        monkeypatch.delenv(var, raising=False)

    c = LLMClient(api_key="test-key", base_url="https://gw/v1")
    fake = _FakeClient()
    c._client = fake  # type: ignore[assignment]
    return c


async def test_timeout_is_a_client_option_not_a_body_field(client):
    """核心回归：timeout 必须是 SDK 的客户端选项，并带正确的语义。

    修复前 ``timeout`` 是 payload 里的一个裸整数，会被序列化进请求体
    发给上游；修复后它是 ``httpx.Timeout`` 对象，作用在传输层。

    两种写法在 dict 里都叫 "timeout"，所以断言的是【类型与语义】，
    而不是"有没有这个键"。
    """
    import httpx

    await _collect(client, [ChatMessage("user", "hi")], timeout=240)

    body = client._client.completions.captured
    assert "timeout" in body
    t = body["timeout"]
    assert isinstance(t, httpx.Timeout), (
        f"timeout 应是 httpx.Timeout（客户端选项），实际是 {type(t).__name__}。"
        "裸整数说明它会被当成 body 字段发给上游，且不会生效。"
    )


async def test_timeout_passed_as_call_parameter(client):
    """timeout 必须以 SDK 调用参数的形式传入。"""
    await _collect(client, [ChatMessage("user", "hi")], timeout=240)

    body = client._client.completions.captured
    assert "timeout" in body, "timeout 必须作为 create() 的参数传入才会生效"

    import httpx

    t = body["timeout"]
    assert isinstance(t, httpx.Timeout)
    assert t.read == 240.0, "读超时应等于调用方指定的值"
    assert t.connect is not None and t.connect <= 15.0, "连接超时应短，便于快速失败"


async def test_no_stray_timeout_field_at_all(client):
    """传了 timeout 也不应污染 body 的键集合。"""
    await _collect(client, [ChatMessage("user", "hi")], timeout=120)

    body = client._client.completions.captured
    allowed = {
        "model", "messages", "stream", "response_format",
        "temperature", "top_p", "max_tokens", "timeout",
    }
    stray = set(body) - allowed
    assert not stray, f"请求体出现非预期字段: {stray}"


async def test_standard_params_still_passed(client):
    """确保修复没有影响其它参数。"""
    await _collect(
        client,
        [ChatMessage("user", "hi")],
        model="m1",
        response_format="json_object",
        temperature=0.7,
        max_tokens=100,
        timeout=60,
    )

    body = client._client.completions.captured
    assert body["model"] == "m1"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 100
    assert body["stream"] is True


async def test_response_format_omitted_when_none(client):
    """response_format=None 时不应发送该字段（Gemini 系模型会因此报错）。"""
    await _collect(client, [ChatMessage("user", "hi")], response_format=None)
    assert "response_format" not in client._client.completions.captured
