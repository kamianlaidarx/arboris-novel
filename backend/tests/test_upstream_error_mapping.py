"""上游错误分类的回归测试。

背景：之前只捕获了 ``InternalServerError``，于是「模型名写错」导致的 404
一路冒到 FastAPI 变成 500，用户只看到「服务器内部错误」，完全看不出
真正原因是配置问题。

这里逐条验证状态码 → 提示文案的映射，重点是：
1. 配置类错误（404/401/400）必须给出**可操作**的提示，而不是笼统的 500；
2. 余额不足要能被识别出来（有的网关用 400/402 表达）；
3. 上游原文要保留，因为它往往已经说明了具体原因。
"""
from __future__ import annotations

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openai import APIStatusError

from app.services.llm_service import (
    _classify_upstream_status,
    _extract_upstream_message,
    _upstream_error_detail,
)


def _make_error(status_code: int, body: dict | str | None = None) -> APIStatusError:
    """构造一个带 response 的 APIStatusError，模拟上游返回。"""
    request = httpx.Request("POST", "https://gw.example/v1/chat/completions")
    if body is None:
        content = b"{}"
    elif isinstance(body, str):
        content = body.encode()
    else:
        import json

        content = json.dumps(body, ensure_ascii=False).encode()
    response = httpx.Response(status_code, request=request, content=content)
    return APIStatusError("upstream error", response=response, body=body)


# ==================================================== 消息提取

def test_extract_prefers_message_zh():
    exc = _make_error(400, {"error": {"message": "bad", "message_zh": "参数有误"}})
    assert _extract_upstream_message(exc) == "参数有误"


def test_extract_falls_back_to_message():
    exc = _make_error(400, {"error": {"message": "Invalid model"}})
    assert _extract_upstream_message(exc) == "Invalid model"


def test_extract_handles_top_level_message():
    exc = _make_error(400, {"message": "顶层消息"})
    assert _extract_upstream_message(exc) == "顶层消息"


def test_extract_returns_none_on_garbage():
    exc = _make_error(400, "not json at all")
    assert _extract_upstream_message(exc) is None


def test_extract_returns_none_when_no_message_key():
    exc = _make_error(400, {"error": {"code": "x"}})
    assert _extract_upstream_message(exc) is None


# ==================================================== 状态码分类

def test_404_model_not_found_is_actionable():
    """核心场景：模型名写错。必须提示「检查模型名」而不是 500。"""
    exc = _make_error(404, {"error": {"message": "model not found"}})
    code, detail = _classify_upstream_status(exc, "deepseek-flash")

    assert code == 400, "应作为使用者可修正的错误返回，而不是 500"
    assert "deepseek-flash" in detail, "提示里要指明是哪个模型"
    assert "不存在" in detail
    assert "模型名" in detail


def test_401_invalid_key():
    exc = _make_error(401, {"error": {"message": "Invalid API key"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 401
    assert "API Key" in detail


def test_403_permission_includes_upstream_text():
    exc = _make_error(403, {"error": {"message": "model not enabled"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 403
    assert "model not enabled" in detail, "上游原文应保留，它已说明原因"


def test_429_rate_limit():
    exc = _make_error(429, {"error": {"message": "too many requests"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 429
    assert "限流" in detail


def test_500_maps_to_503():
    exc = _make_error(500, {"error": {"message": "internal"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 503


@pytest.mark.parametrize("status", [502, 503, 504])
def test_all_5xx_map_to_503(status):
    exc = _make_error(status, {"error": {"message": "bad gateway"}})
    code, _ = _classify_upstream_status(exc, "m")
    assert code == 503


def test_400_with_balance_message_becomes_402():
    """有的网关用 400 表达余额不足，要识别出来给更准确的提示。"""
    exc = _make_error(400, {"error": {"message": "Insufficient Balance"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 402
    assert "余额" in detail


def test_402_balance():
    exc = _make_error(402, {"error": {"message": "Insufficient Balance"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 402
    assert "余额" in detail


def test_400_without_balance_stays_generic():
    exc = _make_error(400, {"error": {"message": "invalid temperature"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 400
    assert "invalid temperature" in detail


def test_422_maps_to_400():
    exc = _make_error(422, {"error": {"message": "unprocessable"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 400
    assert "unprocessable" in detail


def test_unknown_status_uses_502():
    exc = _make_error(418, {"error": {"message": "teapot"}})
    code, detail = _classify_upstream_status(exc, "m")
    assert code == 502
    assert "418" in detail


def test_no_model_name_still_produces_message():
    """模型名为空时文案不能出现「当前模型「None」」。"""
    exc = _make_error(404, {"error": {"message": "nope"}})
    code, detail = _classify_upstream_status(exc, None)
    assert code == 400
    assert "None" not in detail


def test_upstream_detail_falls_back_when_no_message():
    exc = _make_error(500, None)
    assert _upstream_error_detail(exc, "兜底文案") == "兜底文案"


def test_upstream_detail_prefers_upstream_text():
    exc = _make_error(500, {"error": {"message": "upstream said so"}})
    assert _upstream_error_detail(exc, "兜底") == "upstream said so"
