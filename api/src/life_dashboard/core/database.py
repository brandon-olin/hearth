import logging
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)


def _migrations_dir() -> Path:
    """Locate the Alembic script directory in both source and frozen layouts.

    Source: api/src/life_dashboard/core/database.py → api/migrations.
    Frozen (PyInstaller / Tauri): bundled at the root of the extraction dir by
    the `datas` entry in life_dashboard.spec.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "migrations"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[3] / "migrations"


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
        #
        # statement_cache_size=0 disables asyncpg's prepared-statement cache.
        # Without this, any schema change (migration) invalidates cached plans
        # and causes a one-time InvalidCachedStatementError on the first request
        # after a deploy. The small per-query overhead is negligible at this scale.
        return create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=(settings.environment == "development"),
            connect_args={"statement_cache_size": 0},
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


def _stamp_head_if_unversioned(sync_conn) -> None:
    """Stamp a SQLite DB at the current Alembic head if it has no version yet.

    ADR-014 (stamp-at-head, forward-only): a SQLite database is built from
    current ORM metadata by create_all(), which is by definition equivalent to
    head.  Recording that fact means historical revisions never replay, and
    every *future* revision runs normally via `alembic upgrade head`.

    Idempotent: once alembic_version holds a revision, this is a no-op, so
    subsequent boots never clobber a version advanced by a real upgrade.
    """
    script = ScriptDirectory(str(_migrations_dir()))
    context = MigrationContext.configure(sync_conn)

    if context.get_current_revision() is not None:
        return

    context.stamp(script, "head")
    logger.info("SQLite database stamped at Alembic head %s", script.get_current_head())


async def create_all_tables() -> None:
    """Create all tables from ORM metadata and stamp at head (SQLite only).

    A fresh SQLite database gets its schema from create_all() rather than by
    replaying 0001-0045, then is stamped at head so future migrations apply
    forward in batch mode.  Postgres uses Alembic exclusively.

    Subsequent calls are idempotent — create_all() skips existing tables and
    the stamp only happens when alembic_version is empty.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_stamp_head_if_unversioned)
