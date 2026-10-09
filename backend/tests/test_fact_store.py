"""时序事实库（FactStore）回归测试。

重点覆盖两类东西：
1. **有效期区间的语义**——「第 N 章时该事实是否成立」必须精确。
2. **失效安全红线**——Synapse 的生产事故显示，无界候选集 + LLM 判定会让
   **70% 仍然为真的事实被静默删除**。因此这里逐条验证各种「不该失效」的情形。
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
from app.models.memory_layer import CharacterState
from app.models.narrative_fact import NarrativeFact
from app.models.novel import NovelProject
from app.services.fact_store import (
    FactStore,
    backfill_from_character_state,
    render_facts_block,
    _is_more_specific,
)


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
        await s.commit()
        yield s
    await engine.dispose()
    os.unlink(tmp.name)


async def _record_location(store: FactStore, content: str, chapter: int, **kw):
    return await store.record(
        project_id="p1",
        entity_id="沈墨",
        fact_type="location",
        content=content,
        chapter_number=chapter,
        **kw,
    )


# ------------------------------------------------------- 区间语义

async def test_fact_is_visible_only_within_its_interval(session):
    """受伤(5..11) → 痊愈(12..)，第 8 章看到受伤，第 13 章看到痊愈。"""
    store = FactStore(session)

    await store.record(
        project_id="p1", entity_id="沈墨", fact_type="state",
        content="左臂刀伤未愈", chapter_number=5, importance="critical",
    )
    await store.record(
        project_id="p1", entity_id="沈墨", fact_type="state",
        content="左臂刀伤已痊愈", chapter_number=12,
        importance="critical", supersede=True,
    )

    at8 = await store.facts_at("p1", 8)
    assert [f.content for f in at8] == ["左臂刀伤未愈"]

    at11 = await store.facts_at("p1", 11)
    assert [f.content for f in at11] == ["左臂刀伤未愈"]

    at12 = await store.facts_at("p1", 12)
    assert [f.content for f in at12] == ["左臂刀伤已痊愈"]

    at13 = await store.facts_at("p1", 13)
    assert [f.content for f in at13] == ["左臂刀伤已痊愈"]

    # 第 5 章之前什么都没有
    assert await store.facts_at("p1", 4) == []


async def test_open_ended_fact_stays_valid_forever(session):
    store = FactStore(session)
    await store.record(
        project_id="p1", entity_id="沈墨", fact_type="ability",
        content="实力：凝气三层", chapter_number=3,
    )
    for chapter in (3, 50, 500):
        facts = await store.facts_at("p1", chapter)
        assert [f.content for f in facts] == ["实力：凝气三层"]


async def test_entity_filter(session):
    store = FactStore(session)
    await store.record(project_id="p1", entity_id="沈墨", fact_type="location",
                       content="位于破庙", chapter_number=2)
    await store.record(project_id="p1", entity_id="苏晚", fact_type="location",
                       content="位于渡口", chapter_number=2)

    only_shen = await store.facts_at("p1", 5, entities=["沈墨"])
    assert [f.entity_id for f in only_shen] == ["沈墨"]


# ------------------------------------------------------- 失效安全红线

async def test_supersede_sets_valid_until_to_previous_chapter(session):
    store = FactStore(session)
    old = await _record_location(store, "位于破庙", 5)
    out = await _record_location(store, "位于渡口客栈", 9, supersede=True)

    assert out.superseded_count == 1
    assert out.superseded[0].id == old.fact.id
    assert out.superseded[0].valid_until == 8      # 第 9 章改变 → 有效到第 8 章
    assert out.superseded[0].superseded_by_id == out.fact.id


async def test_manual_facts_are_never_auto_superseded(session):
    """人工录入的事实永不自动失效——这是硬性保护。"""
    store = FactStore(session)
    await _record_location(store, "位于破庙", 5, extracted_by="manual")
    out = await _record_location(store, "位于渡口客栈", 9, supersede=True)

    assert out.superseded_count == 0
    # 第 9 章两条都还在（人工那条仍然有效）
    at9 = await store.facts_at("p1", 9, include_minor=True)
    assert {f.content for f in at9} == {"位于破庙", "位于渡口客栈"}


async def test_more_general_new_fact_does_not_supersede_specific_old_one(session):
    """Synapse 实测最常见的误删：更笼统的新事实把更具体的真事实顶掉。"""
    store = FactStore(session)
    await store.record(
        project_id="p1", entity_id="沈墨", fact_type="ability",
        content="实力：凝气三层，可御剑飞行", chapter_number=3,
    )
    out = await store.record(
        project_id="p1", entity_id="沈墨", fact_type="ability",
        content="实力：凝气三层", chapter_number=9, supersede=True,
    )

    assert out.superseded_count == 0, "更笼统的新事实不得失效旧事实"
    at9 = await store.facts_at("p1", 9)
    # 两条都仍然有效——旧的没有被静默删掉
    contents = {f.content for f in at9}
    assert contents == {"实力：凝气三层，可御剑飞行", "实力：凝气三层"}
    # 而且原来那条具体的仍然未失效
    assert any(f.content == "实力：凝气三层，可御剑飞行" and f.valid_until is None for f in at9)


async def test_restatement_does_not_supersede(session):
    """同义改写也不得触发失效。"""
    store = FactStore(session)
    await store.record(project_id="p1", entity_id="沈墨", fact_type="location",
                       content="位于破庙之中", chapter_number=5)
    out = await store.record(project_id="p1", entity_id="沈墨", fact_type="location",
                             content="位于破庙", chapter_number=9, supersede=True)
    assert out.superseded_count == 0


async def test_supersede_only_touches_same_entity_and_type(session):
    """候选集必须严格限定在「同实体 + 同类型」，不能误伤别的实体。"""
    store = FactStore(session)
    await store.record(project_id="p1", entity_id="苏晚", fact_type="location",
                       content="位于渡口", chapter_number=5)
    await store.record(project_id="p1", entity_id="沈墨", fact_type="state",
                       content="身体状态：受伤", chapter_number=5)

    out = await _record_location(store, "位于破庙", 9, supersede=True)

    assert out.superseded_count == 0
    other = await store.facts_at("p1", 9, entities=["苏晚"])
    assert [f.content for f in other] == ["位于渡口"]


async def test_supersede_ignores_future_and_same_chapter_facts(session):
    store = FactStore(session)
    future = await _record_location(store, "位于未来之地", 20)
    out = await _record_location(store, "位于破庙", 9, supersede=True)

    assert out.superseded_count == 0
    assert future.fact.valid_until is None, "不得失效未来章节的事实"


async def test_already_superseded_fact_is_not_touched_again(session):
    store = FactStore(session)
    await _record_location(store, "位于破庙", 5)
    await _record_location(store, "位于渡口客栈", 9, supersede=True)
    # 再改一次
    out = await _record_location(store, "位于江边渡口", 15, supersede=True)

    assert out.superseded_count == 1
    assert out.superseded[0].valid_until == 14
    assert out.superseded[0].content == "位于渡口客栈"


# ------------------------------------------------------- 幂等与校验

async def test_duplicate_record_is_idempotent(session):
    store = FactStore(session)
    first = await _record_location(store, "位于破庙", 5)
    second = await _record_location(store, "位于破庙", 5)

    assert first.created is True
    assert second.created is False
    assert second.fact.id == first.fact.id


async def test_invalid_fact_type_rejected(session):
    store = FactStore(session)
    with pytest.raises(ValueError, match="fact_type"):
        await store.record(project_id="p1", entity_id="沈墨", fact_type="nonsense",
                           content="x", chapter_number=1)


async def test_empty_content_rejected(session):
    store = FactStore(session)
    with pytest.raises(ValueError, match="不能为空"):
        await _record_location(store, "   ", 1)


# ------------------------------------------------------- 推导函数

def test_specificity_helper():
    assert _is_more_specific("位于破庙深处的地窖", "位于破庙") is True   # 细化
    assert _is_more_specific("位于破庙", "位于破庙深处的地窖") is False  # 更笼统
    assert _is_more_specific("位于破庙", "位于破庙") is False            # 完全相同
    assert _is_more_specific("", "x") is False


# ------------------------------------------------------- 约束块渲染

async def test_render_constraints_contains_facts_and_header(session):
    store = FactStore(session)
    await store.record(project_id="p1", entity_id="沈墨", fact_type="state",
                       content="左臂刀伤未愈", chapter_number=5, importance="critical")
    block = await store.render_constraints("p1", 8)

    assert "第8章" in block
    assert "左臂刀伤未愈" in block
    assert "【沈墨】" in block
    assert "!" in block          # critical 标记


async def test_render_constraints_empty_when_no_facts(session):
    store = FactStore(session)
    assert await store.render_constraints("p1", 1) == ""


def test_render_facts_block_handles_empty_list():
    assert render_facts_block([], 5) == ""


# ------------------------------------------------------- 从一期状态派生

async def test_backfill_derives_facts_from_character_state(session):
    """一期写入的结构化状态应能零成本派生成事实。"""
    session.add(
        CharacterState(
            project_id="p1", character_id=0, character_name="沈墨",
            chapter_number=5, location="破庙", health_status="injured",
            injuries=["左臂刀伤"], inventory=["短刀", "火折子"],
            power_level="凝气三层",
        )
    )
    await session.commit()

    written = await backfill_from_character_state(session, "p1", 5)
    assert written >= 4

    store = FactStore(session)
    facts = await store.facts_at("p1", 5, include_minor=True)
    contents = {f.content for f in facts}
    assert "位于破庙" in contents
    assert any("左臂刀伤" in c for c in contents)
    assert any("短刀" in c for c in contents)
    assert "实力：凝气三层" in contents

    # 第 4 章时这些事实都还不存在
    assert await store.facts_at("p1", 4, include_minor=True) == []


async def test_backfill_then_progress_updates_interval(session):
    """第 5 章受伤 → 第 12 章痊愈，区间应正确切换。"""
    session.add(CharacterState(
        project_id="p1", character_id=0, character_name="沈墨",
        chapter_number=5, health_status="injured", injuries=["左臂刀伤"],
    ))
    await session.commit()
    await backfill_from_character_state(session, "p1", 5)

    session.add(CharacterState(
        project_id="p1", character_id=0, character_name="沈墨",
        chapter_number=12, health_status="healthy",
    ))
    await session.commit()
    await backfill_from_character_state(session, "p1", 12)

    store = FactStore(session)
    at8 = {f.content for f in await store.facts_at("p1", 8)}
    assert any("左臂刀伤" in c for c in at8)

    # 「痊愈」是 minor 重要度（默认状态不该占 P0 约束块），所以查全部重要度。
    # 关键断言：受伤那条在这里必须【不再有效】——这正是区间切换在起作用。
    at12_all = {f.content for f in await store.facts_at("p1", 12, include_minor=True)}
    assert any("健康" in c for c in at12_all)
    assert not any("左臂刀伤" in c for c in at12_all), "痊愈后不应再报告旧伤"

    # 默认（只看 critical/major）在第 12 章应当没有身体状态约束了
    at12_p0 = {f.content for f in await store.facts_at("p1", 12)}
    assert not any("左臂刀伤" in c for c in at12_p0)
