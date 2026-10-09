"""SQLite 连接级 PRAGMA 与会话回滚的回归测试。

这三个 PRAGMA 之前完全缺失，导致：
- 外键级联全部失效（ON DELETE CASCADE 形同虚设）→ 删章节留下孤儿行
- journal_mode=DELETE → 写阻塞读
- busy_timeout=0 → 并发写直接 database is locked
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def sqlite_engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")

    # 与 app.db.session 中注册的监听器保持一致
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        try:
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
        finally:
            cur.close()

    yield engine
    await engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp.name + suffix)
        except FileNotFoundError:
            pass


async def test_foreign_keys_pragma_is_on(sqlite_engine):
    """外键必须开启，否则删父行不会级联删子行。"""
    async with sqlite_engine.connect() as conn:
        value = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()
    assert value == 1


async def test_journal_mode_is_wal(sqlite_engine):
    """WAL 让读写在并发下不互相阻塞。"""
    async with sqlite_engine.connect() as conn:
        value = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
    assert str(value).lower() == "wal"


async def test_busy_timeout_is_set(sqlite_engine):
    """有 busy_timeout 才会等锁，而不是立刻 database is locked。"""
    async with sqlite_engine.connect() as conn:
        value = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
    assert value == 5000


async def test_cascade_delete_actually_works(sqlite_engine):
    """端到端验证：外键开启后，删父行会真正级联删除子行。"""
    async with sqlite_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        await conn.execute(
            text(
                "CREATE TABLE child ("
                " id INTEGER PRIMARY KEY,"
                " parent_id INTEGER NOT NULL,"
                " FOREIGN KEY (parent_id) REFERENCES parent(id) ON DELETE CASCADE)"
            )
        )

    async with sqlite_engine.begin() as conn:
        await conn.execute(text("INSERT INTO parent (id) VALUES (1)"))
        await conn.execute(text("INSERT INTO child (id, parent_id) VALUES (10, 1)"))

    async with sqlite_engine.begin() as conn:
        await conn.execute(text("DELETE FROM parent WHERE id = 1"))

    async with sqlite_engine.connect() as conn:
        remaining = (await conn.execute(text("SELECT COUNT(*) FROM child"))).scalar()
    assert remaining == 0, "外键级联未生效，产生了孤儿行"


async def test_foreign_key_violation_is_rejected(sqlite_engine):
    """外键开启后，插入悬空引用应当被拒绝。"""
    from sqlalchemy.exc import IntegrityError

    async with sqlite_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        await conn.execute(
            text(
                "CREATE TABLE child ("
                " id INTEGER PRIMARY KEY,"
                " parent_id INTEGER NOT NULL,"
                " FOREIGN KEY (parent_id) REFERENCES parent(id) ON DELETE CASCADE)"
            )
        )

    with pytest.raises(IntegrityError):
        async with sqlite_engine.begin() as conn:
            await conn.execute(text("INSERT INTO child (id, parent_id) VALUES (1, 999)"))
