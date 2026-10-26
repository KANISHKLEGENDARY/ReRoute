"""
Pytest root configuration and test isolation fixtures.

Enforces:
1. Tests always use their own separate database (in-memory SQLite), never the real one.
2. Safety check: Immediately aborts tests if the database engine ever points to the real database.
3. Redis isolation: Prevents simulated events in tests from leaking onto the live Redis channel.
"""

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock
import pytest

# Windows AppLocker fallback for uuid_utils if native .pyd is blocked
try:
    import uuid_utils  # noqa: F401
except ImportError:
    m = types.ModuleType("uuid_utils")
    m.UUID, m.uuid1, m.uuid3, m.uuid4, m.uuid5 = uuid.UUID, uuid.uuid1, uuid.uuid3, uuid.uuid4, uuid.uuid5
    m.uuid7, m.uuid8 = lambda: uuid.uuid4(), lambda: uuid.uuid4()
    compat = types.ModuleType("uuid_utils.compat")
    compat.uuid7, compat.UUID = lambda: uuid.uuid4(), uuid.UUID
    m.compat = compat
    sys.modules["uuid_utils"] = m
    sys.modules["uuid_utils.compat"] = compat

# 1. Force tests to use isolated in-memory SQLite, never the live database
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENVIRONMENT"] = "testing"
os.environ["REDIS_CHANNEL"] = "test_flight_events"
os.environ["RUN_LIVE_LLM"] = "0"

# Clear settings cache so all modules load the test configuration
from app.core.config import get_settings
get_settings.cache_clear()

from app.core.database import engine, async_session_factory, check_test_db_safety
from app.models.base import Base


# 2. Safety check: Immediately abort if tests ever point at the real database
@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    check_test_db_safety()


@pytest.fixture(autouse=True, scope="function")
def enforce_test_db_safety():
    """Per-test safety check: assert the engine url is NEVER pointing at the real database."""
    check_test_db_safety()


@pytest.fixture(autouse=True, scope="function")
async def setup_test_db():
    """Ensure all database schema tables exist in the isolated in-memory test database."""
    check_test_db_safety()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
def isolate_redis_events(monkeypatch):
    """
    Prevent tests that hit POST /api/v1/events/simulate from publishing onto the live
    Redis channel consumed by the background worker.
    """
    mock_publish = AsyncMock(return_value=True)
    monkeypatch.setattr("app.core.redis.publish_event", mock_publish)
    monkeypatch.setattr("app.api.v1.simulate.publish_event", mock_publish)
