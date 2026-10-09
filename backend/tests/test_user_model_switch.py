"""多模型切换的回归测试。

重点验证**回退链**，因为这是最容易出错、也最难在界面上发现的地方：

    显式传入的 model > 用户活跃模型 > 旧单模型配置 > 系统默认

任何一环断掉，用户都会遇到「切了模型但没生效」。
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.llm_config import LLMConfig
from app.models.novel import NovelProject
from app.models.system_config import SystemConfig
from app.models.user import User
from app.models.user_llm_model import UserLLMModel
from app.services.user_model_service import UserModelService


@pytest.fixture
async def session():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        from app.core.security import hash_password

        s.add(User(id=1, username="u1", email="u1@e.com",
                   hashed_password=hash_password("x"), is_admin=False))
        await s.commit()
        yield s
    await engine.dispose()
    os.unlink(tmp.name)


async def _set_legacy_config(session, user_id=1, model="legacy-model", key="k-legacy"):
    session.add(LLMConfig(user_id=user_id, llm_provider_url="https://gw/v1",
                          llm_provider_api_key=key, llm_provider_model=model))
    await session.commit()


# ==================================================== 基本 CRUD

async def test_first_added_model_becomes_active(session):
    svc = UserModelService(session)
    rec = await svc.add_model(1, "model-a")
    await session.commit()
    assert rec.is_active is True
    assert await svc.get_active_model(1) == "model-a"


async def test_adding_second_model_does_not_steal_active(session):
    svc = UserModelService(session)
    await svc.add_model(1, "model-a")
    await session.commit()
    await svc.add_model(1, "model-b")
    await session.commit()
    assert await svc.get_active_model(1) == "model-a", "后加的模型不应自动抢走活跃"


async def test_add_is_idempotent(session):
    svc = UserModelService(session)
    a = await svc.add_model(1, "dup")
    await session.commit()
    b = await svc.add_model(1, "dup")
    await session.commit()
    assert a.id == b.id
    models = await svc.list_models(1)
    assert len([m for m in models if m.model_name == "dup"]) == 1


async def test_switch_active(session):
    svc = UserModelService(session)
    await svc.add_model(1, "m1")
    await session.commit()
    m2 = await svc.add_model(1, "m2")
    await session.commit()

    ok = await svc.set_active(1, m2.id)
    await session.commit()
    assert ok is True
    assert await svc.get_active_model(1) == "m2"

    # 关键：不能同时有两个活跃
    models = await svc.list_models(1)
    assert sum(1 for m in models if m.is_active) == 1


async def test_activate_by_name_auto_adds(session):
    """按名称切换时，未收藏的模型应自动加入——前端可直接输入模型名。"""
    svc = UserModelService(session)
    ok = await svc.set_active_by_name(1, "brand-new-model")
    await session.commit()
    assert ok is True
    assert await svc.get_active_model(1) == "brand-new-model"
    names = {m.model_name for m in await svc.list_models(1)}
    assert "brand-new-model" in names


async def test_activate_rejects_other_users_model(session):
    from app.core.security import hash_password

    session.add(User(id=2, username="u2", email="u2@e.com",
                     hashed_password=hash_password("x")))
    await session.commit()

    svc = UserModelService(session)
    mine = await svc.add_model(1, "mine")
    await session.commit()

    assert await svc.set_active(2, mine.id) is False, "不能激活别人的模型"


async def test_remove_active_promotes_next(session):
    svc = UserModelService(session)
    first = await svc.add_model(1, "first")
    await session.commit()
    second = await svc.add_model(1, "second")
    await session.commit()
    assert first.is_active

    await svc.remove_model(1, first.id)
    await session.commit()

    # 删掉活跃项后，剩下的应自动补位
    assert await svc.get_active_model(1) == "second"


async def test_remove_last_model_leaves_none(session):
    svc = UserModelService(session)
    only = await svc.add_model(1, "only")
    await session.commit()
    await svc.remove_model(1, only.id)
    await session.commit()
    assert await svc.get_active_model(1) is None
    assert await svc.list_models(1) == []


async def test_bulk_add_dedupes(session):
    svc = UserModelService(session)
    added = await svc.add_models(1, ["a", "b", "a", "", "  ", "c"])
    await session.commit()
    assert added == 3
    names = sorted(m.model_name for m in await svc.list_models(1))
    assert names == ["a", "b", "c"]


# ==================================================== 旧配置迁移

async def test_seeds_from_legacy_config(session):
    """老用户升级后，原来的单模型配置应自动出现在列表里且为活跃。"""
    await _set_legacy_config(session, model="old-model")
    svc = UserModelService(session)

    models = await svc.list_models(1)
    assert len(models) == 1
    assert models[0].model_name == "old-model"
    assert models[0].is_active is True
    assert await svc.get_active_model(1) == "old-model"


async def test_seed_only_happens_once(session):
    await _set_legacy_config(session, model="old-model")
    svc = UserModelService(session)
    await svc.list_models(1)
    await session.commit()

    # 用户主动删掉后，不应被重复播种
    for m in await svc.list_models(1):
        await svc.remove_model(1, m.id)
    await session.commit()

    models = await svc.list_models(1)
    assert models == [], "删除后不应再次从旧配置播种"


async def test_no_seed_when_legacy_model_empty(session):
    session.add(LLMConfig(user_id=1, llm_provider_url="https://gw/v1",
                          llm_provider_api_key="k", llm_provider_model=None))
    await session.commit()
    svc = UserModelService(session)
    assert await svc.list_models(1) == []


# ==================================================== 回退链（核心）

async def test_active_model_wins_over_legacy(session):
    """活跃模型应覆盖（不代表丢弃）旧单模型配置。"""
    from app.services.llm_service import LLMService

    await _set_legacy_config(session, model="legacy-model")
    svc = UserModelService(session)
    await svc.set_active_by_name(1, "active-model")
    await session.commit()

    resolved = await LLMService(session)._resolve_llm_config(1)
    assert resolved["model"] == "active-model"
    # 凭据仍来自旧表（多模型共用一套凭据）
    assert resolved["api_key"] == "k-legacy"


async def test_explicit_override_beats_active(session):
    """本次请求显式指定的模型优先级最高。"""
    from app.services.llm_service import LLMService

    await _set_legacy_config(session, model="legacy-model")
    svc = UserModelService(session)
    await svc.set_active_by_name(1, "active-model")
    await session.commit()

    resolved = await LLMService(session)._resolve_llm_config(1, model_override="one-off")
    assert resolved["model"] == "one-off"


async def test_falls_back_to_legacy_when_no_active(session):
    from app.services.llm_service import LLMService

    await _set_legacy_config(session, model="legacy-model")
    resolved = await LLMService(session)._resolve_llm_config(1)
    assert resolved["model"] == "legacy-model"


async def test_explicit_override_works_without_any_saved_config(session):
    """显式指定模型时，即使还没设活跃模型也应生效。"""
    from app.services.llm_service import LLMService

    await _set_legacy_config(session, model=None)
    resolved = await LLMService(session)._resolve_llm_config(1, model_override="direct")
    assert resolved["model"] == "direct"


async def test_blank_override_is_ignored(session):
    """空白字符串不应把模型名覆盖成空。"""
    from app.services.llm_service import LLMService

    await _set_legacy_config(session, model="legacy-model")
    for blank in ("", "   ", None):
        resolved = await LLMService(session)._resolve_llm_config(1, model_override=blank)
        assert resolved["model"] == "legacy-model", f"input={blank!r}"


async def test_system_config_used_when_no_user_config(session):
    from app.services.llm_service import LLMService

    session.add(SystemConfig(key="llm.api_key", value="sys-key"))
    session.add(SystemConfig(key="llm.base_url", value="https://sys/v1"))
    session.add(SystemConfig(key="llm.model", value="sys-model"))
    await session.commit()

    resolved = await LLMService(session)._resolve_llm_config(1)
    assert resolved["api_key"] == "sys-key"
    assert resolved["model"] == "sys-model"


async def test_system_model_overridden_by_active(session):
    """没有用户凭据时，活跃模型仍应覆盖系统默认模型名。"""
    from app.services.llm_service import LLMService

    session.add(SystemConfig(key="llm.api_key", value="sys-key"))
    session.add(SystemConfig(key="llm.model", value="sys-model"))
    await session.commit()

    svc = UserModelService(session)
    await svc.set_active_by_name(1, "user-picked")
    await session.commit()

    resolved = await LLMService(session)._resolve_llm_config(1)
    assert resolved["api_key"] == "sys-key"
    assert resolved["model"] == "user-picked"
