import logging
from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)


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


def _patch_sqlite_schema(sync_conn) -> None:
    """
    Inspect the live SQLite schema and ADD COLUMN for any model column that
    is missing from the actual table.

    SQLAlchemy's create_all() creates new tables but never alters existing
    ones.  This fills that gap so that adding a column to a model (e.g.
    group_id on budget_categories) is picked up automatically on the next
    restart — no manual ALTER TABLE needed.

    Limitations (acceptable for SQLite dev):
    - NOT NULL columns with no DEFAULT are added as nullable; SQLite would
      reject the constraint on an already-populated table anyway.
    - Columns with UNIQUE constraints are skipped (SQLite can't add those
      via ALTER TABLE).
    - Primary key columns are skipped (never makes sense to add post-hoc).

    Safe to call on every boot — the inspect() check makes it idempotent.
    """
    insp = inspect(sync_conn)
    existing_tables = set(insp.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # brand-new table; create_all() handles it

        existing_cols = {col["name"] for col in insp.get_columns(table.name)}

        for col in table.columns:
            if col.name in existing_cols:
                continue
            if col.primary_key:
                continue  # never add a PK after the fact
            if any(isinstance(c, type(col)) and c.unique for c in col.constraints):
                logger.warning(
                    "SQLite schema patch: skipping %s.%s — UNIQUE columns "
                    "cannot be added via ALTER TABLE",
                    table.name, col.name,
                )
                continue

            try:
                col_type_str = col.type.compile(dialect=sync_conn.dialect)
            except Exception:
                col_type_str = "TEXT"

            # Build DEFAULT clause.  If the column is NOT NULL but has no
            # server_default, fall back to DEFAULT NULL so SQLite accepts it.
            if col.server_default is not None:
                default_clause = f" DEFAULT {col.server_default.arg}"
            elif not col.nullable:
                default_clause = " DEFAULT NULL"
            else:
                default_clause = ""

            sql = (
                f"ALTER TABLE {table.name} "
                f"ADD COLUMN {col.name} {col_type_str}{default_clause}"
            )
            try:
                sync_conn.execute(text(sql))
                sync_conn.commit()
                logger.info(
                    "SQLite schema patch: added %s.%s (%s)",
                    table.name, col.name, col_type_str,
                )
            except Exception as exc:
                # Column may have appeared between the inspect() call and now,
                # or the type is genuinely unsupported — either way, log and move on.
                logger.warning(
                    "SQLite schema patch: could not add %s.%s — %s",
                    table.name, col.name, exc,
                )


async def create_all_tables() -> None:
    """Create all tables from ORM metadata (SQLite path only).

    On SQLite there are no Alembic migrations to run — the schema is
    created fresh on first boot via this function.  Postgres continues to
    use Alembic migrations as normal.  Subsequent calls are idempotent
    (create_all skips tables that already exist).

    After create_all(), _patch_sqlite_schema() adds any columns that are in
    the ORM models but missing from the live DB — so adding a mapped column
    never requires a manual ALTER TABLE in the dev SQLite workflow.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Auto-patch missing columns (SQLite only — Postgres uses Alembic).
    async with engine.connect() as conn:
        await conn.run_sync(_patch_sqlite_schema)
