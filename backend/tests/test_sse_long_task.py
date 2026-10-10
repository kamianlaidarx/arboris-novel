"""长任务 SSE 工具的回归测试。

背景：Arboris 有若干耗时远超 100 秒的端点（蓝图生成实测 160 秒，
章节生成更久）。Cloudflare 免费版对「源站 100 秒未响应」返回 524，
且面板无法调大——触发条件是【首字节等待时间】，一旦开始传输就重置。

所以两类保活手段都要验证：
  1. 尽快发出首帧（让计时重置）
  2. 任务执行期间持续发心跳（避免模型长时间不出字造成静默）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException

import app.utils.sse as sse_mod
from app.utils.sse import (
    HEARTBEAT_FRAME,
    run_with_heartbeat,
    sse_event,
    sse_response,
)


# ==================================================== 帧编码

def test_heartbeat_frame_is_comment():
    """心跳必须是注释帧：以 ':' 开头，客户端按规范忽略。"""
    assert HEARTBEAT_FRAME.startswith(":")
    assert HEARTBEAT_FRAME.endswith("\n\n")


def test_sse_event_chinese_unescaped():
    frame = sse_event("done", {"msg": "生成完成"})
    assert "生成完成" in frame
    assert "\\u" not in frame


def test_sse_event_escapes_newlines():
    frame = sse_event("done", {"text": "a\nb"})
    body = frame.split("data: ", 1)[1].rsplit("\n\n", 1)[0]
    assert json.loads(body)["text"] == "a\nb"
    assert frame.count("\n") == 3


def test_sse_response_headers_disable_buffering():
    """关缓冲是让首字节立刻到达、从而重置代理计时的关键。"""
    resp = sse_response(_empty_gen())
    assert resp.media_type == "text/event-stream"
    assert resp.headers.get("x-accel-buffering") == "no"
    assert resp.headers.get("cache-control") == "no-cache"


async def _empty_gen():
    if False:
        yield ""


# ==================================================== 心跳行为

async def _collect(work, label="t"):
    return [f async for f in run_with_heartbeat(work, on_done=lambda r: r, label=label)]


async def test_fast_task_emits_only_done(monkeypatch):
    monkeypatch.setattr(sse_mod, "HEARTBEAT_INTERVAL_SECONDS", 10.0)

    async def quick():
        await asyncio.sleep(0.05)
        return {"ok": True}

    frames = await _collect(quick)
    assert len(frames) == 1, "快任务不应产生心跳"
    assert frames[0].startswith("event: done")


async def test_slow_task_emits_heartbeats(monkeypatch):
    """核心：任务执行期间必须有心跳，否则连接会被判定为空闲。"""
    monkeypatch.setattr(sse_mod, "HEARTBEAT_INTERVAL_SECONDS", 0.2)

    async def slow():
        await asyncio.sleep(0.75)
        return {"ok": "slow"}

    frames = await _collect(slow)
    beats = [f for f in frames if f.startswith(":")]
    assert len(beats) >= 2, f"慢任务应产生多个心跳，实际 {len(beats)}"
    assert frames[-1].startswith("event: done")


async def test_result_is_dict_payload(monkeypatch):
    monkeypatch.setattr(sse_mod, "HEARTBEAT_INTERVAL_SECONDS", 10.0)

    async def work():
        return {"blueprint": {"title": "测试"}, "ai_message": "好了"}

    frames = await _collect(work)
    payload = json.loads(frames[-1].split("data: ", 1)[1].strip())
    assert payload["blueprint"]["title"] == "测试"


async def test_http_exception_becomes_error_event(monkeypatch):
    """响应头已发出，不可能改状态码，只能以事件形式告知。"""
    monkeypatch.setattr(sse_mod, "HEARTBEAT_INTERVAL_SECONDS", 10.0)

    async def boom():
        raise HTTPException(status_code=404, detail="模型不存在")

    frames = await _collect(boom)
    assert frames[-1].startswith("event: error")
    payload = json.loads(frames[-1].split("data: ", 1)[1].strip())
    assert payload["detail"] == "模型不存在"
    assert payload["status"] == 404


async def test_unexpected_exception_becomes_error_event(monkeypatch):
    monkeypatch.setattr(sse_mod, "HEARTBEAT_INTERVAL_SECONDS", 10.0)

    async def boom():
        raise RuntimeError("内部炸了")

    frames = await _collect(boom)
    assert frames[-1].startswith("event: error")
    assert "内部炸了" in frames[-1]


# ==================================================== 路由注册

def test_all_long_endpoints_have_stream_variant():
    """容易漏的地方：加了实现但忘了注册路由，前端仍走非流式。"""
    from app.main import app

    paths = {r.path for r in app.routes}
    expected = [
        "/api/novels/{project_id}/concept/converse-stream",
        "/api/novels/{project_id}/blueprint/generate-stream",
        "/api/writer/advanced/generate-stream",
        "/api/writer/novels/{project_id}/chapters/generate-stream",
        "/api/writer/novels/{project_id}/chapters/evaluate-stream",
        "/api/writer/novels/{project_id}/chapters/outline-stream",
        "/api/optimizer/optimize-stream",
    ]
    for p in expected:
        assert p in paths, f"缺少流式端点: {p}"


def test_original_endpoints_kept():
    """流式是新增，不应删掉原有端点（外部契约不能破坏）。"""
    from app.main import app

    paths = {r.path for r in app.routes}
    for p in (
        "/api/novels/{project_id}/blueprint/generate",
        "/api/writer/novels/{project_id}/chapters/generate",
        "/api/optimizer/optimize",
    ):
        assert p in paths, f"原端点被误删: {p}"
