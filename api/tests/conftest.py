import os

# life_dashboard.core.settings.Settings requires DATABASE_URL and JWT_SECRET_KEY
# with no defaults. Importing almost any life_dashboard module (even for pure
# unit tests with no DB) transitively imports settings at module load time, so
# these must be set before any life_dashboard import happens. conftest.py is
# loaded by pytest before test modules in this directory, so setting them here
# (via setdefault, so a real .env / real env still wins) covers every test file.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.main  # noqa: F401  (registers all ORM models on Base.metadata)
from life_dashboard.core.database import Base


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session

    await engine.dispose()
