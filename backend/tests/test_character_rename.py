"""角色改名的预览与应用。

这是全项目风险最高的写操作：它直接改正文。所以测试的重点不是
「能不能改」，而是**改错的时候能不能挡住**：

  - 会合并两个角色的映射必须拒绝
  - 仍是蓝图角色的名字必须拒绝（该去改蓝图而不是替换下游）
  - 正文必须新建版本而不是覆盖，否则原稿永久丢失
  - 预览必须真的不改数据
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
from app.models.novel import (
    BlueprintCharacter,
    Chapter,
    ChapterOutline,
    ChapterVersion,
    NovelProject,
)
from app.services.character_rename_service import CharacterRenameService


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


async def _chars(session, names: List[str]) -> None:
    for i, n in enumerate(names):
        session.add(BlueprintCharacter(project_id="p1", name=n, position=i))
    await session.commit()


async def _outline(session, number: int, title: str, summary: str) -> None:
    session.add(ChapterOutline(
        project_id="p1", chapter_number=number, title=title, summary=summary,
    ))
    await session.commit()


async def _chapter(session, number: int, content: str) -> Chapter:
    ch = Chapter(project_id="p1", chapter_number=number)
    session.add(ch)
    await session.commit()
    v = ChapterVersion(chapter_id=ch.id, content=content, version_label="v1")
    session.add(v)
    await session.commit()
    ch.selected_version_id = v.id
    ch.word_count = len(content)
    await session.commit()
    return ch


# ==================================================== 预览是只读的

async def test_preview_does_not_modify_anything(session):
    await _chars(session, ["李明"])
    await _outline(session, 1, "第一章", "陆行舟出场")
    ch = await _chapter(session, 1, "陆行舟走在街上。陆行舟停下。")

    svc = CharacterRenameService(session)
    preview = await svc.preview("p1", {"陆行舟": "王五"})

    assert preview.total_replacements > 0
    # 数据必须原样
    o = (await session.execute(select(ChapterOutline))).scalars().one()
    assert o.summary == "陆行舟出场"
    v = (await session.execute(select(ChapterVersion))).scalars().one()
    assert "陆行舟" in v.content


async def test_preview_reports_locations_and_samples(session):
    await _chars(session, ["李明"])
    await _outline(session, 3, "第三章", "陆行舟出场")
    await _chapter(session, 3, "陆行舟走在街上")

    preview = await CharacterRenameService(session).preview("p1", {"陆行舟": "王五"})

    targets = {(o.chapter_number, o.target) for o in preview.occurrences}
    assert (3, "outline") in targets
    assert (3, "prose") in targets
    # 必须给出上下文，否则用户无法判断该不该改
    assert any(o.samples for o in preview.occurrences)
    assert preview.affected_outline_chapters == [3]
    assert preview.affected_chapter_numbers == [3]


# ==================================================== 安全护栏

async def test_allows_mapping_old_name_onto_blueprint_character(session):
    """主要用法：把过期旧名对齐到当前蓝图角色，必须允许。

    蓝图主角是「李明」，而大纲里还写着改名前的「陆行舟」，
    用户填「陆行舟 → 李明」正是要修正这个不一致。

    早期版本错误地拒绝了它（理由是「会把两个角色合并」），
    导致用户做任何有意义的改名都得到「没有找到可替换的内容」。
    合并只会发生在【新旧名都是蓝图角色】时，这里旧名根本不是蓝图角色。
    """
    await _chars(session, ["李明", "苏宛"])
    await _outline(session, 1, "第一章", "陆行舟出场")

    preview = await CharacterRenameService(session).preview("p1", {"陆行舟": "李明"})
    assert preview.mapping == {"陆行舟": "李明"}
    assert not preview.rejected
    assert preview.total_replacements > 0


async def test_rejects_renaming_current_blueprint_character(session):
    """旧名仍是蓝图角色 → 拒绝：应该去改蓝图，而不是替换下游文本。"""
    await _chars(session, ["陆行舟", "苏宛"])
    await _outline(session, 1, "第一章", "陆行舟出场")

    preview = await CharacterRenameService(session).preview("p1", {"陆行舟": "王五"})
    assert preview.mapping == {}
    assert "仍是当前蓝图中的角色" in preview.rejected[0]["reason"]


async def test_rejects_identical_names(session):
    await _chars(session, ["李明"])
    preview = await CharacterRenameService(session).preview("p1", {"陆行舟": "陆行舟"})
    assert preview.mapping == {}


async def test_apply_refuses_when_any_mapping_rejected(session):
    """有被拒项时整体不执行，避免用户以为全改了其实只改了一半。"""
    await _chars(session, ["李明", "苏宛"])
    await _outline(session, 1, "第一章", "陆行舟出场")
    await _outline(session, 2, "第二章", "旧名出场")

    svc = CharacterRenameService(session)
    with pytest.raises(ValueError):
        # 李明是蓝图角色 → 作为旧名会被拒，整批不执行
        await svc.apply("p1", {"陆行舟": "王五", "李明": "赵六"})

    # 一个都不该改
    o = (await session.execute(
        select(ChapterOutline).where(ChapterOutline.chapter_number == 2)
    )).scalars().one()
    assert o.summary == "旧名出场"


# ==================================================== 应用

async def test_apply_updates_outlines(session):
    await _chars(session, ["李明"])
    await _outline(session, 1, "陆行舟的觉醒", "陆行舟破解了案件")

    result = await CharacterRenameService(session).apply("p1", {"陆行舟": "王五"})

    o = (await session.execute(select(ChapterOutline))).scalars().one()
    assert o.title == "王五的觉醒"
    assert o.summary == "王五破解了案件"
    assert result.outlines_updated == 1
    assert result.replacements == 2


async def test_apply_creates_new_version_not_overwrite(session):
    """核心安全保证：正文改动必须新建版本，原稿永远可回退。"""
    await _chars(session, ["李明"])
    ch = await _chapter(session, 1, "陆行舟走在街上。")
    original_version_id = ch.selected_version_id

    result = await CharacterRenameService(session).apply("p1", {"陆行舟": "王五"})

    versions = (await session.execute(
        select(ChapterVersion).where(ChapterVersion.chapter_id == ch.id)
    )).scalars().all()
    assert len(versions) == 2, "应新建一个版本而不是覆盖"
    # 原版必须完好
    original = next(v for v in versions if v.id == original_version_id)
    assert original.content == "陆行舟走在街上。"
    # 新版本是替换后的内容
    await session.refresh(ch)
    assert ch.selected_version_id != original_version_id
    new_version = next(v for v in versions if v.id == ch.selected_version_id)
    assert new_version.content == "王五走在街上。"
    assert result.new_version_ids == [new_version.id]


async def test_apply_marks_new_version_source(session):
    """新版本要标记来源，便于日后区分「AI 生成」与「改名产生」。"""
    await _chars(session, ["李明"])
    ch = await _chapter(session, 1, "陆行舟走在街上。")
    await CharacterRenameService(session).apply("p1", {"陆行舟": "王五"})

    await session.refresh(ch)
    v = await session.get(ChapterVersion, ch.selected_version_id)
    assert v.metadata.get("source") == "character_rename"
    assert v.metadata.get("mapping") == {"陆行舟": "王五"}


async def test_apply_updates_word_count(session):
    await _chars(session, ["李明"])
    ch = await _chapter(session, 1, "陆行舟走在街上。")
    await CharacterRenameService(session).apply("p1", {"陆行舟": "王五"})

    await session.refresh(ch)
    assert ch.word_count == len("王五走在街上。")


async def test_apply_can_skip_prose(session):
    """只改大纲：让用户先看效果，确认后再动正文。"""
    await _chars(session, ["李明"])
    await _outline(session, 1, "第一章", "陆行舟出场")
    ch = await _chapter(session, 1, "陆行舟走在街上。")

    result = await CharacterRenameService(session).apply(
        "p1", {"陆行舟": "王五"}, include_prose=False
    )

    o = (await session.execute(select(ChapterOutline))).scalars().one()
    assert o.summary == "王五出场"
    await session.refresh(ch)
    v = await session.get(ChapterVersion, ch.selected_version_id)
    assert v.content == "陆行舟走在街上。", "include_prose=False 时正文不应改动"
    assert result.chapters_updated == 0


async def test_apply_multiple_mappings(session):
    await _chars(session, ["李明"])
    await _outline(session, 1, "第一章", "陆行舟与苏晚相遇")

    await CharacterRenameService(session).apply("p1", {"陆行舟": "王五", "苏晚": "赵六"})

    o = (await session.execute(select(ChapterOutline))).scalars().one()
    assert o.summary == "王五与赵六相遇"


async def test_apply_no_match_is_safe(session):
    """要替换的名字不存在时不报错、不产生版本。"""
    await _chars(session, ["李明"])
    await _outline(session, 1, "第一章", "无关内容")
    ch = await _chapter(session, 1, "无关正文")

    result = await CharacterRenameService(session).apply("p1", {"陆行舟": "王五"})
    assert result.replacements == 0
    assert result.chapters_updated == 0
    versions = (await session.execute(
        select(ChapterVersion).where(ChapterVersion.chapter_id == ch.id)
    )).scalars().all()
    assert len(versions) == 1, "没匹配到就不该新建版本"


async def test_chapter_without_selected_version_is_skipped(session):
    """没有选中版本的章节（未生成正文）不应报错。"""
    await _chars(session, ["李明"])
    session.add(Chapter(project_id="p1", chapter_number=9))
    await session.commit()

    result = await CharacterRenameService(session).apply("p1", {"陆行舟": "王五"})
    assert result.chapters_updated == 0


async def test_empty_mapping_rejected(session):
    await _chars(session, ["李明"])
    with pytest.raises(ValueError):
        await CharacterRenameService(session).apply("p1", {})
