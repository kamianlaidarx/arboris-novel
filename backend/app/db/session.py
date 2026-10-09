# AIMETA P=数据库会话_异步会话工厂|R=异步会话_连接池|NR=不含查询逻辑|E=AsyncSessionLocal_get_db|X=internal|A=会话工厂|D=sqlalchemy|S=db|RD=./README.ai
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ..core.config import settings

# 根据不同数据库驱动调整连接池参数，确保在多数据库环境下表现稳定
engine_kwargs = {"echo": settings.debug}
if settings.is_sqlite_backend:
    # SQLite 场景下禁用连接池并放宽线程检查，避免多协程读写冲突
    engine_kwargs.update(
        pool_pre_ping=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
else:
    # MySQL 场景保持健康检查与连接复用，适用于生产环境的长连接需求
    engine_kwargs.update(pool_pre_ping=True, pool_recycle=3600)

engine = create_async_engine(settings.sqlalchemy_database_uri, **engine_kwargs)


if settings.is_sqlite_backend:
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        """SQLite 每条连接都必须单独设置的三个 PRAGMA。

        缺了它们会出三类真实故障：
        1. foreign_keys 默认为 OFF —— schema.sql 里所有 ``ON DELETE CASCADE``
           根本不生效，而 ``delete_chapters`` 用的是核心 ``delete()``（不加载子对象，
           ORM 级联也不触发），删除章节后会留下孤儿 chapter_versions /
           chapter_evaluations 行。
        2. journal_mode 默认为 DELETE —— 写操作会阻塞所有读操作。
           WAL 下读写可以并发。
        3. busy_timeout 默认 0 —— 并发写入直接抛
           ``database is locked``，而不是等待锁释放。
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


# 统一的 Session 工厂，禁用 expire_on_commit 方便返回模型对象
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖项：提供一个作用域内共享的数据库会话。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            # 请求处理中抛异常时显式回滚，避免把未提交的写挂在下一次复用上。
            await session.rollback()
            raise
