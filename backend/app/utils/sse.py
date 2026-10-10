# AIMETA P=SSE工具_长任务流式响应|R=事件编码_心跳_长任务包装|NR=不含业务逻辑|E=sse_event/run_with_heartbeat|X=internal|A=工具函数|D=fastapi|S=net|RD=./README.ai
"""
长任务的 SSE 支撑工具。

为什么需要
----------
Cloudflare 免费版对「源站 100 秒未响应」返回 524，且面板无法调大。
触发条件是【首字节等待时间】——只要开始传输就会重置。

Arboris 有若干耗时远超 100 秒的端点（蓝图生成实测 160 秒，
章节生成更久）。它们原本都是攒完才返回，必然被掐断。
把它们改成 SSE 后首字节 1~2 秒内发出，限制不再触发。

两类工具
--------
1. :func:`sse_event` —— 把 (event, data) 编码成一帧 SSE。
2. :func:`run_with_heartbeat` —— 在长任务执行期间周期性发送注释帧，
   避免「模型侧长时间不出字」导致的静默（那同样会被代理按静默超时掐断）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, TypeVar

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: 心跳间隔。远小于反向代理的静默超时（Cloudflare 100s），
#: 也小于 nginx 的 proxy_read_timeout。
HEARTBEAT_INTERVAL_SECONDS = 10.0

#: SSE 注释帧。以 ':' 开头，客户端按规范会忽略，仅用于保活连接。
HEARTBEAT_FRAME = ": keep-alive\n\n"


def sse_event(event: str, data: Any) -> str:
    """把一个事件编码成 SSE 帧。

    ``ensure_ascii=False`` 让中文按原样发送，省带宽也便于排查；
    SSE 规范要求 data 内不能有裸换行，因此统一转义为字面量 ``\\n``。
    """
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("\n", "\\n")
    return f"event: {event}\ndata: {payload}\n\n"


async def run_with_heartbeat(
    work: Callable[[], Awaitable[T]],
    *,
    on_done: Callable[[T], Dict[str, Any]],
    label: str = "task",
) -> AsyncIterator[str]:
    """执行一个长任务，期间持续发送心跳帧，完成后发出 ``done`` 事件。

    这样做的意义：即使模型侧长时间不出字（实测有 26 秒静默的案例，
    极端情况更久），连接也一直有数据流动，不会被按静默超时掐断。

    异常处理：``HTTPException`` 转成 ``error`` 事件——响应头已经发出，
    不可能再改 HTTP 状态码，只能以事件形式告知客户端。
    """
    task = asyncio.create_task(work())
    try:
        while True:
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(task), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
                break
            except asyncio.TimeoutError:
                # 任务还在跑：发一个注释帧保持连接活跃
                yield HEARTBEAT_FRAME
    except HTTPException as exc:
        logger.warning("%s 失败: detail=%s", label, exc.detail)
        yield sse_event("error", {"detail": str(exc.detail), "status": exc.status_code})
        return
    except Exception as exc:  # noqa: BLE001 - 兜底，避免连接中断后无提示
        logger.exception("%s 异常", label)
        yield sse_event("error", {"detail": f"{label}失败：{exc}"})
        return

    try:
        yield sse_event("done", on_done(result))
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s 结果序列化失败", label)
        yield sse_event("error", {"detail": f"结果处理失败：{exc}"})


def sse_response(generator: AsyncIterator[str]) -> StreamingResponse:
    """把异步生成器包装成标准的 SSE 响应。"""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            # 关掉各级缓冲，确保首字节立刻到达浏览器——
            # 这是让反向代理不按静默超时掐断的关键。
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

def register_stream_route(
    router,
    path: str,
    *,
    label: str,
    original: Callable[..., Awaitable[Any]],
):
    """为已有端点注册一个 ``-stream`` 变体。

    相比装饰器，这里显式传入 router 与路径，避免「装饰器不知道自己该挂在
    哪个路由上」的问题；同时复用 ``original`` 的签名，让 FastAPI 的路径
    参数与依赖注入（session / current_user）照常生效。

    流式版本不重复实现业务逻辑，只是把原函数放进后台任务并持续发心跳。
    """
    import inspect

    async def _stream(*args, **kwargs):
        async def _gen():
            async def _work():
                result = await original(*args, **kwargs)
                if hasattr(result, "model_dump"):
                    return result.model_dump()
                return result

            async for frame in run_with_heartbeat(
                _work,
                on_done=lambda r: r if isinstance(r, dict) else {"result": r},
                label=label,
            ):
                yield frame

        return sse_response(_gen())

    _stream.__signature__ = inspect.signature(original)  # type: ignore[attr-defined]
    _stream.__name__ = f"{original.__name__}_stream"
    router.post(path, name=f"{original.__name__}_stream")(_stream)
    return _stream
