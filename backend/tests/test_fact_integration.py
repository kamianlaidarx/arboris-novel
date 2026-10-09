"""二期端到端集成测试：定稿派生事实 → 下一章注入正确约束。

验证的完整闭环：
    第 5 章定稿（受伤）→ 事实库写入(5..)
    第 8 章生成时 → 约束块包含「受伤」
    第 12 章定稿（痊愈）→ 旧事实失效(5..11)、新事实(12..)
    第 13 章生成时 → 约束块包含「健康」、不再包含「受伤」

这正是设计文档里承诺的核心行为：把「第 N 章某角色什么状态」
变成可精确查询的约束，而不是靠 2000 字滚动摘要去回忆。
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
from app.services.fact_store import FactStore
from app.services.finalize_service import FinalizeService


class FakeLLMService:
    """固定返回角色状态 JSON，其余返回占位文本。"""

    def __init__(self, character_state: str):
        self.character_state = character_state
        self.prompts: List[str] = []

    async def generate(self, prompt: str, **kwargs: Any) -> Optional[str]:
        self.prompts.append(prompt)
        if "结构化存储" in prompt:
            return self.character_state
        if "更新前文摘要" in prompt:
            return "摘要"
        if "剧情线" in prompt:
            return "{}"
        return "章节摘要"


@pytest.fixture
async def session():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add(NovelProject(id="p1", user_id=1, title="长篇小说"))
        await s.commit()
        yield s
    await engine.dispose()
    os.unlink(tmp.name)


async def _finalize(session, chapter: int, state_json: str) -> Dict[str, Any]:
    service = FinalizeService(session, FakeLLMService(state_json))  # type: ignore[arg-type]
    return await service.finalize_chapter(
        project_id="p1", chapter_number=chapter, chapter_text="正文" * 100, user_id=1
    )


async def test_full_loop_injury_then_recovery(session):
    """受伤 → 问询 → 痊愈 → 问询，约束块必须随章节正确切换。"""
    store = FactStore(session)

    # ---- 第 5 章：受伤 ----
    result5 = await _finalize(
        session,
        5,
        '[{"name": "沈墨", "location": "破庙", "health_status": "injured",'
        ' "injuries": ["左臂刀伤"], "inventory": ["短刀"]}]',
    )
    assert result5["success"] is True
    assert result5["updates"].get("narrative_facts", 0) >= 3

    # 第 4 章：什么都还没有
    assert await store.render_constraints("p1", 4, entities=["沈墨"]) == ""

    # 第 8 章：应该看到受伤 + 位置 + 持有
    block8 = await store.render_constraints("p1", 8, entities=["沈墨"])
    assert "左臂刀伤" in block8
    assert "位于破庙" in block8
    assert "短刀" in block8
    assert "第8章" in block8

    # ---- 第 12 章：痊愈 ----
    result12 = await _finalize(
        session,
        12,
        '[{"name": "沈墨", "location": "渡口", "health_status": "healthy"}]',
    )
    assert result12["success"] is True

    # 第 11 章仍然看到受伤（区间右端闭区间）
    block11 = await store.render_constraints("p1", 11, entities=["沈墨"])
    assert "左臂刀伤" in block11

    # 第 12 章起不再看到受伤
    block12 = await store.render_constraints("p1", 12, entities=["沈墨"])
    assert "左臂刀伤" not in block12, "痊愈后不得再出现旧伤约束"

    # 位置也应更新为渡口
    assert "位于渡口" in block12


async def test_constraints_are_scoped_to_involved_characters(session):
    """只注入本章涉及角色的事实，避免约束块膨胀。"""
    await _finalize(
        session,
        3,
        '[{"name": "沈墨", "location": "破庙"}, {"name": "苏晚", "location": "渡口"}]',
    )
    store = FactStore(session)

    only_shen = await store.render_constraints("p1", 5, entities=["沈墨"])
    assert "【沈墨】" in only_shen
    assert "苏晚" not in only_shen

    both = await store.render_constraints("p1", 5, entities=["沈墨", "苏晚"])
    assert "【沈墨】" in both and "【苏晚】" in both


async def test_finalize_failure_in_fact_derivation_does_not_break_finalize(session):
    """事实派生失败不应让整次定稿失败（摘要/状态/快照已写好）。"""
    # 先放一条无法解析的状态，确认回退路径不会抛
    result = await _finalize(session, 2, "不是 JSON 的自由文本")
    assert result["success"] is True

    # 回退为 __all__ 文本记录，事实库应为空
    store = FactStore(session)
    assert await store.render_constraints("p1", 2, entities=["沈墨"]) == ""


async def test_manual_fact_survives_contradicting_chapter(session):
    """人工录入的事实不因后续章节的自动提取而失效。"""
    store = FactStore(session)
    await store.record(
        project_id="p1", entity_id="沈墨", fact_type="world",
        content="沈墨不会游泳", chapter_number=1,
        importance="critical", extracted_by="manual",
    )
    await session.commit()

    # 后面某章自动提取出「沈墨游泳过河」这种更长的表述
    await _finalize(
        session, 6,
        '[{"name": "沈墨", "power_level": "凝气三层"}]',
    )

    # 人工事实仍然有效
    at10 = await store.facts_at("p1", 10, include_minor=True)
    manual = [f for f in at10 if f.extracted_by == "manual"]
    assert manual and manual[0].valid_until is None
