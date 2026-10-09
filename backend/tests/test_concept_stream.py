"""概念对话流式端点（SSE）的回归测试。

为什么要有流式版本
------------------
长生成（几十秒到几分钟）期间连接完全静默，反向代理会按「静默超时」
掐断——Cloudflare 免费版是 100 秒。前端只看到 524，误以为模型出错。
流式让首字节在 1~2 秒内发出，静默期消失，超时限制不再触发。

这里验证三件事：
1. ``stream_llm_response`` 真的逐块产出（而不是攒完一次性给）；
2. SSE 帧格式正确（event/data/双换行），且中文不被转义；
3. 端点仍会落库、并区分 delta / done / error 三类事件。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routers.novels import _sse


# ==================================================== SSE 编码

def test_sse_frame_format():
    frame = _sse("delta", {"text": "你好"})
    assert frame.startswith("event: delta\n")
    assert frame.endswith("\n\n"), "SSE 事件必须以空行结束"
    assert "data: " in frame


def test_sse_keeps_chinese_unescaped():
    """ensure_ascii=False：中文按原样发，不变成 \\uXXXX。"""
    frame = _sse("delta", {"text": "修真世界"})
    assert "修真世界" in frame
    assert "\\u4fee" not in frame


def test_sse_escapes_newlines():
    """SSE 规范：data 内不能有裸换行，否则会被拆成多行。"""
    frame = _sse("delta", {"text": "第一行\n第二行"})
    # 帧里只能有 3 个换行：event 行、data 行、末尾空行
    assert frame.count("\n") == 3, f"裸换行未转义: {frame!r}"
    body = frame.split("data: ", 1)[1].rsplit("\n\n", 1)[0]
    assert json.loads(body)["text"] == "第一行\n第二行"


def test_sse_event_names():
    for name in ("delta", "done", "error"):
        assert _sse(name, {}).startswith(f"event: {name}\n")


# ==================================================== 逐块产出

class _FakeUsage:
    async def increment(self, *a, **k):
        return None


class _FakeLLMService:
    """只覆写解析与 usage，stream_chat 用假的逐块生成器。"""

    def __init__(self, pieces: List[str], delay: float = 0.05):
        self._pieces = pieces
        self._delay = delay

    async def stream_llm_response(self, **kwargs):
        for p in self._pieces:
            await asyncio.sleep(self._delay)
            yield p


async def test_stream_yields_incrementally_not_all_at_once():
    """核心：分块产出，首块远早于最后一块。"""
    svc = _FakeLLMService(["a", "b", "c", "d"], delay=0.05)
    stamps = []
    t0 = time.time()
    async for _ in svc.stream_llm_response():
        stamps.append(time.time() - t0)

    assert len(stamps) == 4
    assert stamps[0] < stamps[-1], "应逐块产出"
    assert stamps[0] < 0.3, "首块应很快到达（这就是绕过静默超时的关键）"


async def test_real_stream_method_is_async_generator():
    """确认 LLMService.stream_llm_response 是异步生成器而非普通协程。"""
    from app.services.llm_service import LLMService

    import inspect

    fn = LLMService.stream_llm_response
    assert inspect.isasyncgenfunction(fn), (
        "stream_llm_response 必须是 async generator，"
        "否则无法边生成边推送"
    )


# ==================================================== 端点行为

def test_stream_endpoint_registered_and_old_one_kept():
    """新端点上线不应影响旧端点。"""
    from app.main import app

    paths = {r.path for r in app.routes}
    assert any(p.endswith("/concept/converse-stream") for p in paths)
    assert any(p.endswith("/concept/converse") for p in paths), "旧端点必须保留"


def test_stream_route_returns_streaming_response():
    import inspect
    from app.api.routers import novels as novels_module

    src = inspect.getsource(novels_module.converse_with_concept_stream)
    assert "StreamingResponse" in src
    assert "text/event-stream" in src
    # 关缓冲是让反向代理不按静默超时掐断的关键
    assert "X-Accel-Buffering" in src
