"""章节大纲的按范围重新生成。

原有端点只能追加（从最后一章往后接），蓝图改完后无法重做已有大纲。
这里验证新的「生成草稿 → 预览 → 确认 → 应用」流程。

重点在**安全边界**：生成阶段绝不能写数据库，否则预览就失去意义——
几十上百条大纲一次性被覆盖是不可逆的。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.novel import (
    Chapter,
    ChapterOutline,
    ChapterVersion,
    NovelBlueprint,
    NovelProject,
)
from app.services.outline_regen_service import (
    MAX_CHAPTERS_PER_REQUEST,
    OutlineRegenService,
)


class FakePromptService:
    async def get_prompt(self, name: str) -> str:
        return "你是大纲生成器"


class FakeLLM:
    """返回可配置的 JSON，用于验证解析与预览。"""

    def __init__(self, chapters: Optional[List[Dict[str, Any]]] = None, raw: Optional[str] = None):
        self._chapters = chapters if chapters is not None else []
        self._raw = raw
        self.last_prompt: str = ""

    async def get_llm_response(self, *, system_prompt: str, conversation_history, **kw) -> str:
        self.last_prompt = conversation_history[0]["content"]
        if self._raw is not None:
            return self._raw
        return json.dumps({"chapters": self._chapters}, ensure_ascii=False)


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
        s.add(NovelBlueprint(project_id="p1", title="测试", revision=3))
        await s.commit()
        yield s
    await engine.dispose()
    os.unlink(tmp.name)


async def _outline(session, number: int, title: str, summary: str = "旧摘要") -> None:
    session.add(ChapterOutline(
        project_id="p1", chapter_number=number, title=title, summary=summary,
    ))
    await session.commit()


async def _chapter_with_prose(session, number: int, text: str = "正文") -> None:
    ch = Chapter(project_id="p1", chapter_number=number)
    session.add(ch)
    await session.commit()
    v = ChapterVersion(chapter_id=ch.id, content=text, version_label="v1")
    session.add(v)
    await session.commit()
    ch.selected_version_id = v.id
    await session.commit()


def _drafts(start: int, count: int, prefix: str = "新标题") -> List[Dict[str, Any]]:
    return [
        {"chapter_number": start + i, "title": f"{prefix}{start+i}", "summary": f"新摘要{start+i}"}
        for i in range(count)
    ]


# ==================================================== 生成阶段不写库

async def test_generate_does_not_write_anything(session):
    """核心安全保证：生成只产出草稿，绝不落库。"""
    await _outline(session, 1, "旧标题")

    svc = OutlineRegenService(session)
    preview = await svc.generate(
        "p1", start_chapter=1, num_chapters=2,
        llm_service=FakeLLM(_drafts(1, 2)), prompt_service=FakePromptService(),
    )

    assert len(preview.drafts) == 2
    # 数据库里必须还是旧内容
    o = (await session.execute(select(ChapterOutline))).scalars().one()
    assert o.title == "旧标题", "生成阶段不应修改数据库"
    assert o.summary == "旧摘要"


async def test_generate_reports_existing_for_comparison(session):
    """预览要带上旧内容，否则用户无从对比。"""
    await _outline(session, 1, "旧标题", "旧摘要")

    preview = await OutlineRegenService(session).generate(
        "p1", start_chapter=1, num_chapters=1,
        llm_service=FakeLLM(_drafts(1, 1)), prompt_service=FakePromptService(),
    )

    d = preview.drafts[0]
    assert d.existing_title == "旧标题"
    assert d.existing_summary == "旧摘要"
    assert d.is_new is False
    assert d.changed is True


async def test_generate_marks_new_chapters(session):
    """原本没有的章节要标为新增，而不是「覆盖」。"""
    preview = await OutlineRegenService(session).generate(
        "p1", start_chapter=5, num_chapters=2,
        llm_service=FakeLLM(_drafts(5, 2)), prompt_service=FakePromptService(),
    )
    assert all(d.is_new for d in preview.drafts)
    assert preview.overwritten_chapters == []


async def test_generate_flags_chapters_with_prose(session):
    """已有正文的章节必须提示：改大纲会造成新的不一致。"""
    await _outline(session, 1, "旧标题")
    await _chapter_with_prose(session, 1)

    preview = await OutlineRegenService(session).generate(
        "p1", start_chapter=1, num_chapters=1,
        llm_service=FakeLLM(_drafts(1, 1)), prompt_service=FakePromptService(),
    )

    assert preview.chapters_with_prose == [1]
    assert preview.drafts[0].has_prose is True
    assert any("正文" in w for w in preview.warnings)


async def test_chapter_without_selected_version_is_not_prose(session):
    """只是建了章节行、没有选中版本 → 不算有正文。"""
    session.add(Chapter(project_id="p1", chapter_number=1))
    await session.commit()

    preview = await OutlineRegenService(session).generate(
        "p1", start_chapter=1, num_chapters=1,
        llm_service=FakeLLM(_drafts(1, 1)), prompt_service=FakePromptService(),
    )
    assert preview.chapters_with_prose == []


# ==================================================== 输入校验

async def test_rejects_too_many_chapters(session):
    """一次生成过多会变慢且后半段容易丢一致性，必须拦住。"""
    with pytest.raises(ValueError, match="最多"):
        await OutlineRegenService(session).generate(
            "p1", start_chapter=1, num_chapters=MAX_CHAPTERS_PER_REQUEST + 1,
            llm_service=FakeLLM([]), prompt_service=FakePromptService(),
        )


async def test_rejects_zero_or_negative(session):
    svc = OutlineRegenService(session)
    with pytest.raises(ValueError):
        await svc.generate("p1", start_chapter=1, num_chapters=0,
                           llm_service=FakeLLM([]), prompt_service=FakePromptService())
    with pytest.raises(ValueError):
        await svc.generate("p1", start_chapter=0, num_chapters=1,
                           llm_service=FakeLLM([]), prompt_service=FakePromptService())


async def test_rejects_unparseable_response(session):
    with pytest.raises(ValueError, match="JSON"):
        await OutlineRegenService(session).generate(
            "p1", start_chapter=1, num_chapters=1,
            llm_service=FakeLLM(raw="这不是 JSON"),
            prompt_service=FakePromptService(),
        )


async def test_rejects_empty_chapters(session):
    with pytest.raises(ValueError):
        await OutlineRegenService(session).generate(
            "p1", start_chapter=1, num_chapters=1,
            llm_service=FakeLLM([]), prompt_service=FakePromptService(),
        )


# ==================================================== 提示词

async def test_instructions_included_in_prompt(session):
    llm = FakeLLM(_drafts(1, 1))
    await OutlineRegenService(session).generate(
        "p1", start_chapter=1, num_chapters=1,
        instructions="节奏要快，每章结尾留悬念",
        llm_service=llm, prompt_service=FakePromptService(),
    )
    assert "节奏要快" in llm.last_prompt


async def test_keep_existing_false_changes_wording(session):
    """keep_existing=False 要明确告诉模型可以抛开已有大纲。"""
    llm = FakeLLM(_drafts(1, 1))
    await OutlineRegenService(session).generate(
        "p1", start_chapter=1, num_chapters=1, keep_existing=False,
        llm_service=llm, prompt_service=FakePromptService(),
    )
    assert "不必受已有大纲限制" in llm.last_prompt


async def test_prompt_declares_instructions_priority(session):
    """建议必须声明优先级，否则模型会偏向已有大纲。"""
    llm = FakeLLM(_drafts(1, 1))
    await OutlineRegenService(session).generate(
        "p1", start_chapter=1, num_chapters=1, instructions="改得紧凑些",
        llm_service=llm, prompt_service=FakePromptService(),
    )
    assert "优先级高于" in llm.last_prompt


async def test_prompt_specifies_chapter_range(session):
    """要明确章节号范围与数量，否则模型可能少生成或编号错乱。"""
    llm = FakeLLM(_drafts(10, 3))
    await OutlineRegenService(session).generate(
        "p1", start_chapter=10, num_chapters=3,
        llm_service=llm, prompt_service=FakePromptService(),
    )
    assert "10" in llm.last_prompt and "12" in llm.last_prompt
    assert "3" in llm.last_prompt


# ==================================================== 应用

async def test_apply_overwrites_and_stamps_revision(session):
    await _outline(session, 1, "旧标题", "旧摘要")

    result = await OutlineRegenService(session).apply("p1", _drafts(1, 2))

    assert result == {"created": 1, "updated": 1}
    rows = (await session.execute(
        select(ChapterOutline).order_by(ChapterOutline.chapter_number)
    )).scalars().all()
    assert rows[0].title == "新标题1"
    assert rows[0].summary == "新摘要1"
    # 新写的大纲必须标记当前蓝图版本，否则会一直被当成过期
    assert rows[0].blueprint_revision == 3
    assert rows[1].blueprint_revision == 3


async def test_apply_skips_empty_entries(session):
    """标题与摘要都空的条目要跳过，避免写进垃圾数据。"""
    result = await OutlineRegenService(session).apply(
        "p1", [{"chapter_number": 1, "title": "", "summary": ""}]
    )
    assert result == {"created": 0, "updated": 0}


async def test_apply_ignores_invalid_chapter_number(session):
    result = await OutlineRegenService(session).apply(
        "p1", [{"chapter_number": "abc", "title": "x", "summary": "y"}]
    )
    assert result == {"created": 0, "updated": 0}
