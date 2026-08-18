import os
from collections.abc import AsyncIterator

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://globe:globe@localhost:5432/globe_test")
os.environ["CREDENTIAL_ENCRYPTION_KEY"] = TEST_KEY

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

ADMIN_URL = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/postgres"
TEST_DB = os.environ["DATABASE_URL"].rsplit("/", 1)[1]

_schema_ready = False


async def _ensure_database() -> None:
    admin_engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin_engine.dispose()


async def _ensure_schema(engine) -> None:
    global _schema_ready
    from app.models import Base

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)
    _schema_ready = True


@pytest.fixture
async def engine():
    await _ensure_database()
    engine = create_async_engine(os.environ["DATABASE_URL"])
    await _ensure_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE api_credentials, event_weapons, events, event_clusters, "
                "firms_hotspots, ingest_watermarks RESTART IDENTITY CASCADE"
            )
        )
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s
