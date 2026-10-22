"""
This file sets up the database connection when the server starts, and creates
all tables that are defined in the app's models (generic — it doesn't know 
what those tables are for). It also provides a reusable db session ("get_db") 
that other parts of the app use to safely read/write to the database per request.
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool
from app.core.config import get_settings
from app.models.base import Base

settings = get_settings()

if ":memory:" in settings.DATABASE_URL:
    pool_cls = StaticPool
    connect_args = {"check_same_thread": False}
else:
    pool_cls = NullPool
    connect_args = {}

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    poolclass=pool_cls,
    connect_args=connect_args,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


def check_test_db_safety() -> None:
    """
    Safety check: Ensures tests stop immediately if they ever point at the real database.
    Rejects any connection string containing PostgreSQL, asyncpg, or port 5432.
    """
    url_str = str(engine.url).lower()
    dangerous_keywords = ["postgresql", "asyncpg", "5432"]
    for keyword in dangerous_keywords:
        if keyword in url_str:
            raise RuntimeError(
                f"SAFETY CHECK FAILED: Tests are pointing at the real database ({engine.url})! "
                "Tests must use a separate isolated test database (e.g. SQLite :memory:)."
            )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def _migrate_decision_trace_columns(sync_conn):
            try:
                res = sync_conn.exec_driver_sql("PRAGMA table_info(decision_trace)").fetchall()
                col_names = [col[1] for col in res]
                if col_names and "event_id" not in col_names:
                    sync_conn.exec_driver_sql(
                        "ALTER TABLE decision_trace ADD COLUMN event_id VARCHAR(100) DEFAULT 'LEGACY'"
                    )
                    sync_conn.exec_driver_sql(
                        "UPDATE decision_trace SET event_id = printf('LEGACY-%d', id) "
                        "WHERE event_id = 'LEGACY' OR event_id IS NULL"
                    )
            except Exception:
                pass

        await conn.run_sync(_migrate_decision_trace_columns)
