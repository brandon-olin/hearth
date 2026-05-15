from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from life_dashboard.core.settings import settings


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


def _make_engine():
    url = settings.database_url

    if _is_sqlite():
        # SQLite: use aiosqlite driver with NullPool (no connection pooling —
        # aiosqlite manages its own connection lifecycle per operation).
        # check_same_thread=False is required for async use.
        # pool_size / max_overflow are Postgres-only and must not be set here.
        return create_async_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
            echo=(settings.environment == "development"),
        )
    else:
        # Postgres: asyncpg driver, validated pool.
        # pool_pre_ping validates each connection before handing it to a query.
        # Important for long-idle pools — the NAS firewall may silently drop connections.
        return create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=(settings.environment == "development"),
        )


engine = _make_engine()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    # Prevents SQLAlchemy from expiring ORM attributes after commit, which
    # would trigger lazy-load errors in an async context.
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base — all domain models inherit from this."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session and guarantees cleanup."""
    async with AsyncSessionLocal() as session:
        yield session


async def create_all_tables() -> None:
    """Create all tables from ORM metadata (SQLite path only).

    On SQLite there are no Alembic migrations to run — the schema is
    created fresh on first boot via this function.  Postgres continues to
    use Alembic migrations as normal.  Subsequent calls are idempotent
    (create_all skips tables that already exist).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
