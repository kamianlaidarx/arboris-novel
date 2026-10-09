"""FinalizeService 异步化 + 结构化角色状态写回的回归测试。

运行：
    cd backend && ../.venv/bin/python -m pytest tests/test_finalize_structured_state.py -v

覆盖两个已修复的缺陷：
1. 旧实现在 async 上下文中用 sync Session，真实 IO 会抛 MissingGreenlet，
   导致整个定稿流程在第一步就失败（global_summary / plot_arcs / character_state 全都写不进去）。
2. 旧实现把全部角色状态塞进 character_id=0 / character_name="__all__" 的文本 blob，
   结构化列（location / health_status / inventory ...）全部为空、无法查询。
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.memory_layer import CharacterState
from app.models.novel import NovelProject
from app.models.project_memory import ChapterSnapshot, ProjectMemory
from app.services import finalize_service as fs_module
from app.services.finalize_service import FinalizeService, _parse_character_state_payload


# ---------------------------------------------------------------- 测试替身

class FakeLLMService:
    """按提示词内容返回预设响应，避免测试依赖真实 LLM。"""

    def __init__(self, responses: Dict[str, str]):
        self.responses = responses
        self.calls: List[str] = []

    async def generate(self, prompt: str, **kwargs: Any) -> Optional[str]:
        self.calls.append(prompt)
        if "结构化存储" in prompt:              # UPDATE_CHARACTER_STATE_PROMPT
            return self.responses.get("character_state")
        if "更新前文摘要" in prompt:            # UPDATE_GLOBAL_SUMMARY_PROMPT
            return self.responses.get("global_summary")
        if "剧情线" in prompt:                  # UPDATE_PLOT_ARCS_PROMPT
            return self.responses.get("plot_arcs")
        if "摘要" in prompt:                    # 章节摘要
            return self.responses.get("chapter_summary", "本章摘要")
        return "ok"


@pytest.fixture
async def session():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add(NovelProject(id="p1", user_id=1, title="测试小说"))
        await s.commit()
        yield s
    await engine.dispose()
    os.unlink(tmp.name)


# ---------------------------------------------------------------- 解析器

def test_parser_accepts_plain_json_array():
    assert _parse_character_state_payload('[{"name": "沈墨"}]') == [{"name": "沈墨"}]


def test_parser_strips_markdown_fence():
    raw = '```json\n[{"name": "沈墨", "location": "破庙"}]\n```'
    assert _parse_character_state_payload(raw) == [{"name": "沈墨", "location": "破庙"}]


def test_parser_unwraps_characters_key():
    raw = '{"characters": [{"name": "A"}]}'
    assert _parse_character_state_payload(raw) == [{"name": "A"}]


def test_parser_empty_array_means_no_change():
    # 空数组 == 解析成功但没有变更（区别于 None == 解析失败）
    assert _parse_character_state_payload("[]") == []


def test_parser_returns_none_on_garbage():
    assert _parse_character_state_payload("角色名：\n├──物品: 剑") is None
    assert _parse_character_state_payload("") is None


# ---------------------------------------------------------------- 端到端

async def test_finalize_writes_structured_character_state(session):
    """核心回归：定稿必须成功，且角色状态落到结构化列而不是 __all__ blob。"""
    llm = FakeLLMService(
        {
            "global_summary": "全局摘要内容",
            "character_state": (
                '[{"name": "沈墨", "location": "破庙", "health_status": "injured",'
                ' "injuries": ["左臂刀伤"], "emotion": "警觉", "emotion_intensity": 7,'
                ' "inventory": ["短刀", "火折子"], "power_level": "凝气三层"},'
                ' {"name": "苏晚", "location": "渡口", "emotion": "焦虑",'
                ' "emotion_intensity": 5}]'
            ),
            "plot_arcs": '{"unresolved_hooks": [{"id": "h1", "description": "庙外脚步"}],'
                         ' "main_conflicts": [], "character_arcs": []}',
            "chapter_summary": "第五章摘要",
        }
    )
    service = FinalizeService(session, llm)  # type: ignore[arg-type]

    result = await service.finalize_chapter(
        project_id="p1",
        chapter_number=5,
        chapter_text="第五章正文" * 50,
        user_id=1,
    )

    # 1) 定稿整体成功（旧实现在这里会是 MissingGreenlet -> success=False）
    assert result["success"] is True, result
    assert result["updates"].get("character_state") == "updated"

    # 2) 角色状态写进了结构化列
    rows = (
        await session.execute(
            select(CharacterState).where(CharacterState.project_id == "p1")
        )
    ).scalars().all()

    assert rows, "应当写入角色状态"
    assert all(r.character_name != "__all__" for r in rows), "不应再写 __all__ blob"

    by_name = {r.character_name: r for r in rows}
    assert set(by_name) == {"沈墨", "苏晚"}

    shen = by_name["沈墨"]
    assert shen.chapter_number == 5
    assert shen.location == "破庙"
    assert shen.health_status == "injured"
    assert shen.injuries == ["左臂刀伤"]
    assert shen.emotion == "警觉"
    assert shen.emotion_intensity == 7
    assert shen.inventory == ["短刀", "火折子"]
    assert shen.power_level == "凝气三层"

    su = by_name["苏晚"]
    assert su.location == "渡口"
    assert su.emotion == "焦虑"
    # 未提供的字段应给默认值而不是炸掉
    assert su.health_status == "healthy"

    # 3) 全局摘要与剧情线也写入了
    memory = (
        await session.execute(
            select(ProjectMemory).where(ProjectMemory.project_id == "p1")
        )
    ).scalars().first()
    assert memory is not None
    assert memory.global_summary == "全局摘要内容"
    assert memory.last_updated_chapter == 5
    assert memory.plot_arcs and memory.plot_arcs["unresolved_hooks"]

    # 4) 快照创建
    snapshots = (
        await session.execute(
            select(ChapterSnapshot).where(ChapterSnapshot.project_id == "p1")
        )
    ).scalars().all()
    assert len(snapshots) == 1


async def test_state_inherits_from_previous_chapter(session):
    """只写变化字段时，未提及的字段应从上一章继承。"""
    llm5 = FakeLLMService(
        {
            "global_summary": "s5",
            "character_state": '[{"name": "沈墨", "location": "破庙", "health_status": "injured",'
                               ' "inventory": ["短刀"], "power_level": "凝气三层"}]',
            "plot_arcs": "{}",
        }
    )
    await FinalizeService(session, llm5).finalize_chapter(  # type: ignore[arg-type]
        project_id="p1", chapter_number=5, chapter_text="正文", user_id=1
    )

    # 第 6 章只报告位置变化
    llm6 = FakeLLMService(
        {
            "global_summary": "s6",
            "character_state": '[{"name": "沈墨", "location": "渡口"}]',
            "plot_arcs": "{}",
        }
    )
    await FinalizeService(session, llm6).finalize_chapter(  # type: ignore[arg-type]
        project_id="p1", chapter_number=6, chapter_text="正文", user_id=1
    )

    rows = (
        await session.execute(
            select(CharacterState)
            .where(CharacterState.project_id == "p1", CharacterState.chapter_number == 6)
        )
    ).scalars().all()
    assert len(rows) == 1
    shen6 = rows[0]
    assert shen6.location == "渡口"            # 本章变化
    assert shen6.health_status == "injured"    # 继承第 5 章
    assert shen6.inventory == ["短刀"]          # 继承第 5 章
    assert shen6.power_level == "凝气三层"       # 继承第 5 章


async def test_non_json_state_falls_back_without_losing_data(session):
    """模型没按 JSON 返回时，回退为 __all__ 文本记录，且定稿仍成功。"""
    llm = FakeLLMService(
        {
            "global_summary": "s",
            "character_state": "沈墨：\n├──物品: 短刀\n├──状态: 受伤",
            "plot_arcs": "{}",
        }
    )
    result = await FinalizeService(session, llm).finalize_chapter(  # type: ignore[arg-type]
        project_id="p1", chapter_number=3, chapter_text="正文", user_id=1
    )

    assert result["success"] is True
    rows = (
        await session.execute(
            select(CharacterState).where(CharacterState.project_id == "p1")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].character_name == "__all__"
    assert "沈墨" in rows[0].extra["raw_state_text"]


async def test_empty_change_list_writes_nothing(session):
    """模型返回空数组表示本章无状态变更，不应写入垃圾行。"""
    llm = FakeLLMService(
        {"global_summary": "s", "character_state": "[]", "plot_arcs": "{}"}
    )
    result = await FinalizeService(session, llm).finalize_chapter(  # type: ignore[arg-type]
        project_id="p1", chapter_number=2, chapter_text="正文", user_id=1
    )

    assert result["success"] is True
    rows = (
        await session.execute(
            select(CharacterState).where(CharacterState.project_id == "p1")
        )
    ).scalars().all()
    assert rows == []
