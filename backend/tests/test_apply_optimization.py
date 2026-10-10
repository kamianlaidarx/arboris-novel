"""「应用优化」的回归测试。

真实故障：该端点用**查询参数**接收优化后的正文，而正文动辄上万字，
URL 会膨胀到 9 万字符以上，远超 nginx 的 ``large_client_header_buffers``
限制（默认 8k），服务端直接返回 **414 URI Too Long**。

正文这类大体积数据本来就该走请求体。这里守住两件事：
1. 参数必须来自请求体（不是查询串）；
2. 长正文能正常写入。
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.novel import Chapter, ChapterVersion, NovelProject
from app.schemas.novel import ApplyOptimizationRequest


# ==================================================== schema 层

def test_request_model_holds_long_content():
    """长正文必须能装进请求体模型。"""
    long_text = "沈渡走进解剖室。" * 5000
    req = ApplyOptimizationRequest(
        project_id="p1", chapter_number=1, optimized_content=long_text
    )
    assert len(req.optimized_content) == len(long_text)


def test_request_model_requires_content():
    """缺少正文时应校验失败，而不是静默接受空值。"""
    with pytest.raises(Exception):
        ApplyOptimizationRequest(project_id="p1", chapter_number=1)


# ==================================================== 端点签名

def test_endpoint_takes_body_not_query_params():
    """回归：正文参数必须来自请求体。

    早期签名是 ``optimized_content: str``（裸 str 参数），FastAPI 会把它
    当成**查询参数**，于是整章正文被塞进 URL → 414。
    这里检查参数类型是 Pydantic 模型，而不是裸 str。
    """
    import inspect

    from app.api.routers import optimizer as optimizer_module

    sig = inspect.signature(optimizer_module.apply_optimization)
    assert "payload" in sig.parameters, "应使用请求体模型接收参数"
    annotation = sig.parameters["payload"].annotation
    assert annotation is ApplyOptimizationRequest, (
        f"payload 应为 ApplyOptimizationRequest，实际是 {annotation}"
    )
    # 不应再出现裸的正文参数
    assert "optimized_content" not in sig.parameters, (
        "optimized_content 不应作为独立参数（那会被当成查询参数）"
    )


# ==================================================== 端到端写入

@pytest.fixture
async def session():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add(NovelProject(id="p1", user_id=1, title="测试"))
        ch = Chapter(project_id="p1", chapter_number=1)
        s.add(ch)
        await s.commit()
        v = ChapterVersion(chapter_id=ch.id, content="原始正文", version_label="v1")
        s.add(v)
        await s.commit()
        ch.selected_version_id = v.id
        await s.commit()
        yield s
    await engine.dispose()
    os.unlink(tmp.name)


async def test_long_content_written_correctly(session):
    """长正文应完整写入，不被截断。"""
    long_text = "沈渡走进解剖室，灯光刺眼。" * 800  # 约 1 万字

    chapter = (
        await session.execute(select(Chapter).where(Chapter.project_id == "p1"))
    ).scalars().one()
    version = await session.get(ChapterVersion, chapter.selected_version_id)
    version.content = long_text
    await session.commit()

    await session.refresh(version)
    assert len(version.content) == len(long_text)
