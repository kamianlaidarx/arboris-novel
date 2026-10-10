"""蓝图变更的过期检测与一致性扫描。

要解决的真实问题：蓝图改过之后，早先生成的大纲和章节正文仍是旧蓝图的
产物。实测项目「因果死角」蓝图角色是 [沈渡/苏宛/方规/陆沉/齐延年]，
而 82 条大纲和正文用的是「陆行舟」「苏晚」——重叠为零，用户只能自己发现。

两条设计原则需要测试守住：
1. **只检测不改动**：正文是几十万字的心血，自动改写风险远大于收益。
2. **没有依据就不报警**：历史数据没有版本号，归入 unknown 而非 stale，
   否则升级后所有老项目满屏告警，提示会立刻被忽略。
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.novel import (
    BlueprintCharacter,
    Chapter,
    ChapterOutline,
    NovelBlueprint,
    NovelProject,
)
from app.services.blueprint_staleness_service import (
    BlueprintStalenessService,
    _finalize_candidates,
    _surname_of,
)
from app.services.novel_service import NovelService


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
        s.add(NovelBlueprint(project_id="p1", title="测试", revision=1))
        await s.commit()
        yield s
    await engine.dispose()
    os.unlink(tmp.name)


async def _add_chars(session, names: List[str]) -> None:
    for i, n in enumerate(names):
        session.add(BlueprintCharacter(project_id="p1", name=n, position=i))
    await session.commit()


async def _add_outline(session, number: int, title: str, summary: str, rev: Optional[int]) -> None:
    session.add(ChapterOutline(
        project_id="p1", chapter_number=number, title=title,
        summary=summary, blueprint_revision=rev,
    ))
    await session.commit()


async def _add_chapter(session, number: int, summary: str, rev: Optional[int]) -> None:
    session.add(Chapter(
        project_id="p1", chapter_number=number,
        real_summary=summary, blueprint_revision=rev,
    ))
    await session.commit()


# ==================================================== 姓氏提取

def test_surname_single():
    assert _surname_of("陆沉") == "陆"
    assert _surname_of("沈渡") == "沈"


def test_surname_compound():
    """复姓要取两字，否则「欧阳锋」会被拆成姓「欧」。"""
    assert _surname_of("欧阳锋") == "欧阳"
    assert _surname_of("司马懿") == "司马"
    assert _surname_of("上官婉儿") == "上官"


def test_surname_short_name():
    assert _surname_of("李") == "李"
    assert _surname_of("") == ""


# ==================================================== 过期检测

async def test_no_stale_when_revisions_match(session):
    await _add_outline(session, 1, "开端", "s", 1)
    await _add_chapter(session, 1, "正文", 1)

    report = await BlueprintStalenessService(session).get_report("p1")
    assert not report.has_stale
    assert report.stale_outline_chapters == []
    assert report.stale_chapter_numbers == []


async def test_detects_stale_outline_and_chapter(session):
    """核心：蓝图升到 revision 2，revision 1 的产物应被标记过期。"""
    await _add_outline(session, 1, "开端", "s", 1)
    await _add_outline(session, 2, "发展", "s", 2)
    await _add_chapter(session, 1, "正文", 1)
    await _add_chapter(session, 2, "正文", 2)

    bp = await session.get(NovelBlueprint, "p1")
    bp.revision = 2
    await session.commit()

    report = await BlueprintStalenessService(session).get_report("p1")
    assert report.current_revision == 2
    assert report.stale_outline_chapters == [1]
    assert report.stale_chapter_numbers == [1]
    assert report.has_stale


async def test_null_revision_goes_to_unknown_not_stale(session):
    """历史数据没有版本号 → unknown，不能当成过期。

    否则升级后所有老项目都会满屏告警，用户会立刻学会忽略它。
    """
    await _add_outline(session, 1, "旧大纲", "s", None)
    await _add_chapter(session, 1, "旧正文", None)
    bp = await session.get(NovelBlueprint, "p1")
    bp.revision = 5
    await session.commit()

    report = await BlueprintStalenessService(session).get_report("p1")
    assert report.stale_outline_chapters == []
    assert report.stale_chapter_numbers == []
    assert report.unknown_outline_chapters == [1]
    assert report.unknown_chapter_numbers == [1]
    assert not report.has_stale


async def test_no_blueprint_means_no_stale(session):
    """还没有蓝图时无从谈起过期。"""
    session.add(NovelProject(id="p2", user_id=1, title="无蓝图"))
    await session.commit()
    await _add_outline(session, 1, "x", "s", None)

    report = await BlueprintStalenessService(session).get_report("p2")
    assert report.current_revision == 0
    assert not report.has_stale


# ==================================================== revision 递增

async def test_revision_bumps_on_real_change(session):
    await _add_chars(session, ["沈渡"])
    svc = NovelService(session)
    await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()

    before = await svc.get_blueprint_revision("p1")
    # 改角色名
    char = (await session.execute(
        __import__("sqlalchemy").select(BlueprintCharacter).where(BlueprintCharacter.project_id == "p1")
    )).scalars().first()
    char.name = "李明"
    await session.commit()

    bumped = await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()
    assert bumped is True
    assert await svc.get_blueprint_revision("p1") == before + 1


async def test_revision_not_bumped_on_identical_save(session):
    """前端保存会把整份数据重发。若每次都递增，用户只要打开编辑器
    点一下保存，全部章节就会被标记为过期——提示会迅速变成噪音。"""
    await _add_chars(session, ["沈渡"])
    svc = NovelService(session)
    await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()

    before = await svc.get_blueprint_revision("p1")
    bumped = await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()

    assert bumped is False, "内容没变不应递增版本号"
    assert await svc.get_blueprint_revision("p1") == before


async def test_metadata_change_does_not_bump(session):
    """改书名这类纯元信息不该让全部章节过期。"""
    await _add_chars(session, ["沈渡"])
    svc = NovelService(session)
    await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()
    before = await svc.get_blueprint_revision("p1")

    bp = await session.get(NovelBlueprint, "p1")
    bp.title = "换了个书名"
    bp.target_audience = "新读者群"
    await session.commit()

    bumped = await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()
    assert bumped is False, "书名不属于影响下游生成的内容"
    assert await svc.get_blueprint_revision("p1") == before


async def test_world_setting_change_bumps(session):
    """世界观改动会影响正文，必须递增。"""
    await _add_chars(session, ["沈渡"])
    svc = NovelService(session)
    await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()
    before = await svc.get_blueprint_revision("p1")

    bp = await session.get(NovelBlueprint, "p1")
    bp.world_setting = {"key_locations": [{"name": "青云宗"}]}
    await session.commit()

    bumped = await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()
    assert bumped is True
    assert await svc.get_blueprint_revision("p1") == before + 1


# ==================================================== 一致性扫描

async def test_scan_finds_renamed_protagonist(session):
    """复现真实场景：蓝图是「陆沉」，大纲和正文写的是「陆行舟」。"""
    await _add_chars(session, ["陆沉", "苏宛"])
    for i in range(1, 5):
        await _add_outline(session, i, f"第{i}章", "陆行舟破解了一起诡异的案件", 1)
    await _add_chapter(session, 1, "陆行舟戴着乳胶手套，屈指捻起骨渣。陆行舟开口。", 1)

    report = await BlueprintStalenessService(session).scan_names("p1")
    names = [n.name for n in report.unknown_names]
    assert "陆行舟" in names, f"应检出改名前的主角名，实际: {names}"
    assert report.blueprint_characters == ["陆沉", "苏宛"]


async def test_scan_ignores_known_characters(session):
    """蓝图里已有的角色不算异常。"""
    await _add_chars(session, ["陆行舟"])
    for i in range(1, 4):
        await _add_outline(session, i, f"第{i}章", "陆行舟出场", 1)

    report = await BlueprintStalenessService(session).scan_names("p1")
    assert [n.name for n in report.unknown_names] == []


async def test_scan_reports_locations(session):
    """要给出出现位置，用户才能定位去改。"""
    await _add_chars(session, ["陆沉"])
    await _add_outline(session, 3, "第三章", "陆行舟出场", 1)
    await _add_outline(session, 7, "第七章", "陆行舟再出场", 1)

    report = await BlueprintStalenessService(session).scan_names("p1")
    entry = next((n for n in report.unknown_names if n.name == "陆行舟"), None)
    assert entry is not None
    assert sorted(entry.outline_chapters) == [3, 7]


async def test_scan_does_not_modify_data(session):
    """核心约束：扫描是只读的，绝不能改动正文。"""
    await _add_chars(session, ["陆沉"])
    await _add_outline(session, 1, "第一章", "陆行舟出场", 1)
    original = (await session.execute(
        __import__("sqlalchemy").select(ChapterOutline.summary)
    )).scalar_one()

    await BlueprintStalenessService(session).scan_names("p1")

    after = (await session.execute(
        __import__("sqlalchemy").select(ChapterOutline.summary)
    )).scalar_one()
    assert after == original, "扫描不应修改任何数据"


async def test_scan_no_characters_is_safe(session):
    """蓝图还没有角色时不应报错。"""
    await _add_outline(session, 1, "第一章", "某人出场", 1)
    report = await BlueprintStalenessService(session).scan_names("p1")
    assert report.unknown_names == []


# ==================================================== 候选收敛

def test_finalize_filters_noise_then_folds_prefix():
    """先频次过滤、再折叠前缀。顺序反了会一个都不剩。"""
    counts = {
        "陆行舟": 3, "陆行": 3,        # 前缀，应被折叠掉
        "陆行舟破": 1, "陆行舟利": 1,   # 带动词的截断，频次不足
        "陆崇岳": 2, "陆崇": 2,
    }
    result = _finalize_candidates(counts)
    assert set(result) == {"陆行舟", "陆崇岳"}


def test_finalize_requires_min_hits():
    """只出现一次的候选不报，避免噪音。"""
    assert _finalize_candidates({"陆某": 1}) == {}


# ==================================================== 端到端暴露的两个 bug

async def test_detects_rename_to_different_surname(session):
    """回归：改成完全不同姓的名字时也要能检出。

    早期版本用「蓝图角色的姓氏」去搜文本，改名 陆沉 → 李明 后
    姓氏集合变成 {李, 苏}，正文里的「陆行舟」就再也搜不到了——
    而这恰恰是最常见的改名方式。端到端测试直接暴露了这个漏报。

    现在改用通用姓氏表 + 跨章节频次过滤，不再依赖蓝图姓氏。
    """
    await _add_chars(session, ["李明", "苏宛"])  # 已经改过名了
    # 用不同的上下文，贴近真实大纲的写法。若每章都是同一句话，
    # 「陆行舟破」这类截断会与真名频次持平，无法区分。
    contexts = [
        "陆行舟破解了案件",
        "陆行舟追踪线索",
        "陆行舟遭遇伏击",
        "陆行舟提取证据",
    ]
    for i, text in enumerate(contexts, start=1):
        await _add_outline(session, i, f"第{i}章", text, 1)

    report = await BlueprintStalenessService(session).scan_names("p1")
    names = [n.name for n in report.unknown_names]
    assert "陆行舟" in names, f"换成不同姓后仍应检出旧名，实际: {names}"


async def test_known_name_excluded_after_aggregation(session):
    """蓝图里已有的角色不能被报为可疑。"""
    await _add_chars(session, ["陆行舟"])
    for i, text in enumerate(["陆行舟出场", "陆行舟开口", "陆行舟转身", "陆行舟沉默"], start=1):
        await _add_outline(session, i, f"第{i}章", text, 1)

    report = await BlueprintStalenessService(session).scan_names("p1")
    assert [n.name for n in report.unknown_names] == []


async def test_known_name_prefix_not_reported(session):
    """已知角色的前缀/延长也不算可疑（陆行 vs 陆行舟）。"""
    await _add_chars(session, ["陆行舟"])
    for i in range(1, 5):
        await _add_outline(session, i, f"第{i}章", "陆行舟与陆行", 1)

    report = await BlueprintStalenessService(session).scan_names("p1")
    names = [n.name for n in report.unknown_names]
    assert "陆行" not in names, f"已知名的前缀不应单独报出: {names}"


async def test_outline_revision_stamped_even_without_bump(session):
    """回归：只传大纲时也必须标记版本号。

    早期写成「只有 revision 递增时才标记」，于是第二次 patch 只传
    chapter_outline 时指纹未变、不递增，大纲版本号一直是空，
    永远归入「未知」而非「过期」——这个提示对大纲就完全失效了。
    """
    await _add_chars(session, ["陆沉"])
    svc = NovelService(session)
    await svc.bump_blueprint_revision_if_changed("p1")
    await session.commit()

    # 只传大纲，不传角色 —— 指纹不变，不会递增
    await svc.patch_blueprint("p1", {
        "chapter_outline": [{"chapter_number": 1, "title": "第一章", "summary": "s"}]
    })

    outline = (await session.execute(
        __import__("sqlalchemy").select(ChapterOutline).where(ChapterOutline.project_id == "p1")
    )).scalars().one()
    assert outline.blueprint_revision is not None, "只传大纲时也必须标记版本号"
    assert outline.blueprint_revision == await svc.get_blueprint_revision("p1")
