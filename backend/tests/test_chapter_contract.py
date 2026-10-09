"""三期回归测试：章间交接契约 + 确定性规则扫描 + 伏笔触发/回收窗口。

这里最要紧的是**规则扫描**：它是零 LLM 成本的确定性检查，
必须能抓到「上一章刚睡着、下一章醒着发呆」这类真实 bug，
同时不能误报合法的场景切换（否则用户会学会忽略告警）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Any, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.chapter_contract import ChapterContract
from app.models.foreshadowing import Foreshadowing
from app.models.novel import Chapter, NovelProject
from app.services.chapter_contract_service import (
    ChapterContractService,
    _extract_day,
    _parse_contract_payload,
    render_contract_block,
)
from app.services.foreshadowing_tracker_service import (
    ForeshadowingTrackerService,
    _split_trigger_condition,
)


class FakeLLM:
    def __init__(self, payload: Optional[str]):
        self.payload = payload

    async def generate(self, prompt: str, **kwargs: Any) -> Optional[str]:
        return self.payload


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


async def _put_contract(session, chapter: int, **fields) -> ChapterContract:
    contract = ChapterContract(project_id="p1", chapter_number=chapter, **fields)
    session.add(contract)
    await session.commit()
    return contract


# ==================================================== 契约解析

def test_parse_contract_payload_with_fence():
    raw = '```json\n{"location": "破庙", "in_story_time": "第3天 深夜"}\n```'
    assert _parse_contract_payload(raw) == {"location": "破庙", "in_story_time": "第3天 深夜"}


def test_parse_contract_payload_strips_think_tags():
    raw = ' thinking先想一下<｜end▁of▁thinking｜>{"location": "渡口"}  '
    assert _parse_contract_payload(raw) == {"location": "渡口"}


def test_parse_contract_payload_on_garbage():
    assert _parse_contract_payload("这不是 JSON") is None
    assert _parse_contract_payload("") is None
    assert _parse_contract_payload(None) is None


def test_extract_day():
    assert _extract_day("第3天 深夜") == 3
    assert _extract_day("Day 12 evening") == 12
    assert _extract_day("某个傍晚") is None
    assert _extract_day(None) is None


# ==================================================== 规则扫描

async def test_detects_sleep_then_awake_without_time_jump(session):
    """真实 bug：上一章刚睡着，下一章开头醒着发呆，且没有时间跳跃。"""
    await _put_contract(
        session, 12,
        in_story_time="第3天 深夜", location="破庙", scene_continues=False,
        time_jump_hint="none",
        characters=[{"name": "沈墨", "doing": "刚睡着", "location": "破庙"}],
    )
    await _put_contract(
        session, 13,
        in_story_time="第3天 深夜", location="破庙", scene_continues=False,
        time_jump_hint="none",
        characters=[{"name": "沈墨", "doing": "醒着，茫然地盯着黑暗", "location": "破庙"}],
    )

    service = ChapterContractService(session, FakeLLM(None))
    result = await service.check_transition("p1", 12, 13)

    assert result.has_blocker
    kinds = {v.kind for v in result.violations}
    assert "action_contradiction" in kinds


async def test_no_false_positive_when_time_jump_declared(session):
    """标注了时间跳跃就不该报警——合法的次日清晨。"""
    await _put_contract(
        session, 12, time_jump_hint="none", scene_continues=False,
        characters=[{"name": "沈墨", "doing": "刚睡着", "location": "破庙"}],
    )
    await _put_contract(
        session, 13, time_jump_hint="next_morning", scene_continues=False,
        characters=[{"name": "沈墨", "doing": "醒来，推开门", "location": "破庙"}],
    )

    service = ChapterContractService(session, FakeLLM(None))
    result = await service.check_transition("p1", 12, 13)
    assert result.is_clean, f"不应误报：{[v.message for v in result.violations]}"


async def test_no_false_positive_when_scene_continues(session):
    """同一场景连续推进时不报警。"""
    await _put_contract(
        session, 5, scene_continues=False, time_jump_hint="none",
        characters=[{"name": "沈墨", "doing": "刚睡着", "location": "破庙"}],
    )
    await _put_contract(
        session, 6, scene_continues=True, time_jump_hint="none",
        characters=[{"name": "沈墨", "doing": "醒来", "location": "破庙"}],
    )
    service = ChapterContractService(session, FakeLLM(None))
    result = await service.check_transition("p1", 5, 6)
    assert result.is_clean


async def test_detects_location_teleport(session):
    await _put_contract(
        session, 7, scene_continues=False, time_jump_hint="none",
        characters=[{"name": "沈墨", "location": "破庙"}],
    )
    await _put_contract(
        session, 8, scene_continues=False, time_jump_hint="none",
        characters=[{"name": "沈墨", "location": "渡口"}],
    )
    service = ChapterContractService(session, FakeLLM(None))
    result = await service.check_transition("p1", 7, 8)
    kinds = {v.kind for v in result.violations}
    assert "location_teleport" in kinds


async def test_detects_unexplained_injury_recovery(session):
    await _put_contract(
        session, 9, scene_continues=True, time_jump_hint="none",
        characters=[{"name": "沈墨", "physical": "左臂刀伤未愈"}],
    )
    await _put_contract(
        session, 10, scene_continues=True, time_jump_hint="none",
        characters=[{"name": "沈墨", "physical": "正常"}],
    )
    service = ChapterContractService(session, FakeLLM(None))
    result = await service.check_transition("p1", 9, 10)
    kinds = {v.kind for v in result.violations}
    assert "injury_recovered_unexplained" in kinds


async def test_detects_time_regression(session):
    await _put_contract(session, 3, in_story_time="第10天 清晨")
    await _put_contract(session, 4, in_story_time="第5天 傍晚")
    service = ChapterContractService(session, FakeLLM(None))
    result = await service.check_transition("p1", 3, 4)
    assert result.has_blocker
    assert any(v.kind == "time_regression" for v in result.violations)


async def test_missing_contract_does_not_crash(session):
    service = ChapterContractService(session, FakeLLM(None))
    result = await service.check_transition("p1", 1, 2)
    assert result.is_clean


# ==================================================== 提取与渲染

async def test_extract_and_save_from_llm(session):
    payload = (
        '{"in_story_time": "第3天 深夜", "location": "破庙",'
        ' "scene_continues": false, "time_jump_hint": "none",'
        ' "characters": [{"name": "沈墨", "doing": "刚睡着",'
        ' "physical": "左臂刀伤未愈", "location": "破庙"}],'
        ' "open_threads": ["庙外脚步声，未解释"]}'
    )
    service = ChapterContractService(session, FakeLLM(payload))
    contract = await service.extract_and_save(
        project_id="p1", chapter_number=3,
        chapter_text="正文" * 500, user_id=1,
    )

    assert contract is not None
    assert contract.location == "破庙"
    assert contract.time_jump_hint == "none"
    assert contract.characters[0]["doing"] == "刚睡着"
    assert contract.open_threads == ["庙外脚步声，未解释"]
    assert contract.prose_tail and len(contract.prose_tail) <= 800


async def test_manual_contract_is_not_overwritten(session):
    await _put_contract(session, 4, location="人工地点", extracted_by="manual")
    service = ChapterContractService(
        session, FakeLLM('{"location": "自动地点"}')
    )
    contract = await service.extract_and_save(
        project_id="p1", chapter_number=4, chapter_text="正文", user_id=1
    )
    assert contract.location == "人工地点", "人工契约不应被自动提取覆盖"


async def test_render_contract_block_mentions_key_state(session):
    await _put_contract(
        session, 7,
        in_story_time="第3天 深夜", location="破庙", time_jump_hint="none",
        characters=[{
            "name": "沈墨", "location": "破庙", "doing": "刚睡着",
            "physical": "左臂刀伤未愈", "unresolved_intent": "明早去渡口",
        }],
        open_threads=["庙外脚步声"],
    )
    service = ChapterContractService(session, FakeLLM(None))
    block = await service.render_contract("p1", 8)

    assert block is not None
    assert "第7章" in block
    assert "刚睡着" in block
    assert "左臂刀伤未愈" in block
    assert "明早去渡口" in block
    assert "庙外脚步声" in block


async def test_render_contract_returns_none_without_previous(session):
    service = ChapterContractService(session, FakeLLM(None))
    assert await service.render_contract("p1", 1) is None


# ==================================================== 伏笔触发与窗口

def test_split_trigger_condition():
    assert _split_trigger_condition("主角被困地窖 AND 已搜索过壁炉台") == [
        "主角被困地窖", "已搜索过壁炉台"
    ]
    assert _split_trigger_condition("主角被困地窖且已搜索过壁炉台") == [
        "主角被困地窖", "已搜索过壁炉台"
    ]
    assert _split_trigger_condition("单一条件") == ["单一条件"]
    assert _split_trigger_condition("") == []


def test_split_trigger_condition_drops_noise_fragments():
    """过短的碎片（'的'/'了'）会被丢弃，避免噪声造成误命中。"""
    assert _split_trigger_condition("主角到达渡口 且 的") == ["主角到达渡口"]


async def _add_foreshadowing(session, **fields) -> Foreshadowing:
    chapter = Chapter(project_id="p1", chapter_number=fields.get("chapter_number", 3))
    session.add(chapter)
    await session.commit()
    fs = Foreshadowing(
        project_id="p1",
        chapter_id=chapter.id,
        chapter_number=fields.pop("chapter_number", 3),
        content=fields.pop("content", "壁炉上的铁钥匙"),
        type=fields.pop("type", "clue"),
        status=fields.pop("status", "planted"),
        **fields,
    )
    session.add(fs)
    await session.commit()
    return fs


async def test_trigger_matches_when_all_subconditions_present(session):
    await _add_foreshadowing(
        session,
        trigger_condition="主角被困地窖 AND 已搜索过壁炉台",
        name="铁钥匙",
    )
    service = ForeshadowingTrackerService(session, FakeLLM(None), None)
    matched = await service.match_triggers(
        "p1", 20, "本章：主角被困地窖，他想起已搜索过壁炉台，于是去取那把钥匙。"
    )
    assert len(matched) == 1
    assert matched[0].name == "铁钥匙"


async def test_trigger_requires_all_subconditions(session):
    await _add_foreshadowing(
        session, trigger_condition="主角被困地窖 AND 已搜索过壁炉台"
    )
    service = ForeshadowingTrackerService(session, FakeLLM(None), None)
    matched = await service.match_triggers("p1", 20, "本章：主角被困地窖。")
    assert matched == [], "只命中部分子条件不应触发"


async def test_trigger_respects_earliest_payoff_window(session):
    """未到最早回收章节，即使触发条件命中也不提示。"""
    await _add_foreshadowing(
        session,
        trigger_condition="主角被困地窖",
        earliest_payoff_chapter=25,
    )
    service = ForeshadowingTrackerService(session, FakeLLM(None), None)

    early = await service.match_triggers("p1", 10, "主角被困地窖")
    assert early == [], "早于 earliest_payoff_chapter 不应触发"

    late = await service.match_triggers("p1", 26, "主角被困地窖")
    assert len(late) == 1


async def test_foreshadowing_window_blocks_premature_payoff(session):
    """核心：earliest_payoff_chapter 阻止过早回收。

    刻意不设 urgency——否则 urgency>=8 会先命中，走不到窗口判断分支。
    """
    await _add_foreshadowing(
        session, name="真相", target_reveal_chapter=40,
        earliest_payoff_chapter=25, chapter_number=3,
    )
    service = ForeshadowingTrackerService(session, FakeLLM(None), None)

    # 第 6 章：远早于窗口下界，不该出现在任何「该回收」的桶里
    early = await service.get_foreshadowings_for_chapter("p1", 6)
    for bucket in ("urgent", "due_soon", "overdue"):
        assert all(fs.name != "真相" for fs in early[bucket]), (
            f"早于窗口下界不应出现在 {bucket}"
        )
    assert any(fs.name == "真相" for fs in early["related"])

    # 第 38 章：进入窗口（距目标 2 章）
    at_window = await service.get_foreshadowings_for_chapter("p1", 38)
    assert any(fs.name == "真相" for fs in at_window["due_soon"])


async def test_high_urgency_cannot_break_payoff_window(session):
    """高紧迫度也不能突破窗口下界——这是最容易被实现漏掉的一种。"""
    await _add_foreshadowing(
        session, name="早回收陷阱", target_reveal_chapter=40,
        earliest_payoff_chapter=25, chapter_number=3, urgency=9,
    )
    service = ForeshadowingTrackerService(session, FakeLLM(None), None)

    early = await service.get_foreshadowings_for_chapter("p1", 6)
    assert all(fs.name != "早回收陷阱" for fs in early["urgent"]), (
        "高紧迫度不得突破窗口下界"
    )

    # 进入窗口后，高紧迫度让它进 urgent 是合理的
    at_window = await service.get_foreshadowings_for_chapter("p1", 30)
    assert any(fs.name == "早回收陷阱" for fs in at_window["urgent"])


async def test_overdue_detection_sets_flag(session):
    await _add_foreshadowing(
        session, name="旧谜", target_reveal_chapter=10, chapter_number=2,
    )
    service = ForeshadowingTrackerService(session, FakeLLM(None), None)
    result = await service.get_foreshadowings_for_chapter("p1", 30)
    assert any(fs.name == "旧谜" for fs in result["overdue"])
