"""角色改名时同步关系引用的回归测试。

背景：``BlueprintRelationship.character_from/to`` 存的是**角色名字符串**，
不是外键。所以角色一改名，旧关系就指向一个不存在的角色——界面照常显示，
不报任何错，但关系实际已失效。这类静默失效很难被发现，必须有测试兜住。

难点在于「如何识别同一个角色被改名」：前后端都没有稳定的角色 ID
（保存时整批删除重建），只能靠位置推断。所以下面既要验证正常改名，
也要验证**不该改的时候不要乱改**——错配名字比不改更糟。
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.novel import (
    BlueprintCharacter,
    BlueprintRelationship,
    NovelProject,
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
        await s.commit()
        yield s
    await engine.dispose()
    os.unlink(tmp.name)


async def _seed(session, names: List[str], rels: List[tuple]) -> None:
    """写入初始角色与关系。"""
    for i, n in enumerate(names):
        session.add(BlueprintCharacter(project_id="p1", name=n, position=i))
    for i, (a, b, desc) in enumerate(rels):
        session.add(
            BlueprintRelationship(
                project_id="p1", character_from=a, character_to=b,
                description=desc, position=i,
            )
        )
    await session.commit()


async def _rels(session) -> List[tuple]:
    rows = (
        await session.execute(
            select(BlueprintRelationship)
            .where(BlueprintRelationship.project_id == "p1")
            .order_by(BlueprintRelationship.position)
        )
    ).scalars().all()
    return [(r.character_from, r.character_to) for r in rows]


def _chars(*names: str) -> List[Dict[str, Any]]:
    return [{"name": n} for n in names]


# ==================================================== 正常改名

async def test_rename_protagonist_updates_relationships(session):
    """核心场景：主角改名，关系里的引用要跟着变。"""
    await _seed(session, ["沈渡", "苏宛"], [("沈渡", "苏宛", "师徒")])

    svc = NovelService(session)
    await svc.patch_blueprint("p1", {"characters": _chars("李明", "苏宛")})

    assert await _rels(session) == [("李明", "苏宛")], "主角改名未同步到关系"


async def test_rename_updates_both_sides(session):
    """两个角色同时改名，关系的两端都要更新。"""
    await _seed(session, ["沈渡", "苏宛"], [("沈渡", "苏宛", "师徒")])

    svc = NovelService(session)
    await svc.patch_blueprint("p1", {"characters": _chars("李明", "王芳")})

    assert await _rels(session) == [("李明", "王芳")]


async def test_rename_updates_multiple_relationships(session):
    """一个角色出现在多条关系里，全部都要更新。"""
    await _seed(
        session,
        ["沈渡", "苏宛", "陆沉"],
        [("沈渡", "苏宛", "师徒"), ("陆沉", "沈渡", "宿敌"), ("苏宛", "陆沉", "同门")],
    )

    svc = NovelService(session)
    await svc.patch_blueprint("p1", {"characters": _chars("李明", "苏宛", "陆沉")})

    assert await _rels(session) == [
        ("李明", "苏宛"),
        ("陆沉", "李明"),
        ("苏宛", "陆沉"),
    ]


# ==================================================== 不该乱改的情况

async def test_no_rename_leaves_relationships_untouched(session):
    """只是编辑了角色描述、没改名，关系不能被动。"""
    await _seed(session, ["沈渡", "苏宛"], [("沈渡", "苏宛", "师徒")])

    svc = NovelService(session)
    await svc.patch_blueprint(
        "p1",
        {"characters": [{"name": "沈渡", "identity": "剑修"}, {"name": "苏宛"}]},
    )

    assert await _rels(session) == [("沈渡", "苏宛")]


async def test_reorder_does_not_corrupt_names(session):
    """调整角色顺序不应把名字错配到别人头上。

    这是位置推断法的最大风险：顺序一变，第 i 个旧角色就对不上
    第 i 个新角色了。规则是「名字仍在新名单里就算未改名」，所以这里
    不能产生任何改名。
    """
    await _seed(session, ["沈渡", "苏宛"], [("沈渡", "苏宛", "师徒")])

    svc = NovelService(session)
    # 只是把顺序换了一下，名字集合没变
    await svc.patch_blueprint("p1", {"characters": _chars("苏宛", "沈渡")})

    assert await _rels(session) == [("沈渡", "苏宛")], "顺序调整不应改动关系"


async def test_deletion_does_not_rename_others(session):
    """删掉中间一个角色，剩下的不能被误判为改名。"""
    await _seed(
        session,
        ["沈渡", "苏宛", "陆沉"],
        [("沈渡", "苏宛", "师徒"), ("苏宛", "陆沉", "同门")],
    )

    svc = NovelService(session)
    # 删掉中间的「苏宛」
    await svc.patch_blueprint("p1", {"characters": _chars("沈渡", "陆沉")})

    # 沈渡/陆沉 名字都还在，不应被改名；苏宛被删则关系保留原样（指向已删角色，
    # 由前端提示用户处理，而不是猜一个名字塞进去）
    assert await _rels(session) == [("沈渡", "苏宛"), ("苏宛", "陆沉")]


async def test_relationships_in_same_patch_win(session):
    """同一次请求里同时改了角色和关系，应以显式的关系数据为准。"""
    await _seed(session, ["沈渡", "苏宛"], [("沈渡", "苏宛", "师徒")])

    svc = NovelService(session)
    await svc.patch_blueprint(
        "p1",
        {
            "characters": _chars("李明", "苏宛"),
            "relationships": [
                {"character_from": "李明", "character_to": "苏宛", "description": "新描述"}
            ],
        },
    )

    assert await _rels(session) == [("李明", "苏宛")]


# ==================================================== 边界

async def test_no_relationships_is_safe(session):
    """没有关系数据时改名不应报错。"""
    await _seed(session, ["沈渡"], [])

    svc = NovelService(session)
    await svc.patch_blueprint("p1", {"characters": _chars("李明")})

    assert await _rels(session) == []


async def test_empty_names_ignored(session):
    """空名字不参与改名映射，避免把关系改成空字符串。"""
    await _seed(session, ["沈渡", "苏宛"], [("沈渡", "苏宛", "师徒")])

    svc = NovelService(session)
    await svc.patch_blueprint("p1", {"characters": _chars("", "苏宛")})

    assert await _rels(session) == [("沈渡", "苏宛")]


async def test_first_save_with_no_old_characters(session):
    """首次保存角色（之前没有角色）不应触发任何同步。"""
    svc = NovelService(session)
    await svc.patch_blueprint("p1", {"characters": _chars("沈渡", "苏宛")})

    assert await _rels(session) == []
