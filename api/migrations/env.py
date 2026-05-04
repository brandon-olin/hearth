import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import async_engine_from_config

from life_dashboard.core.database import Base
from life_dashboard.core.settings import settings

config = context.config

# Inject the DATABASE_URL from application settings so it is never duplicated
# in alembic.ini.
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Base.metadata accumulates table definitions as domain models are imported.
# Every models module must be imported here for alembic autogenerate to see it.
import life_dashboard.auth.models  # noqa: F401
import life_dashboard.domains.calendar_events.models  # noqa: F401
import life_dashboard.domains.contacts.models  # noqa: F401
import life_dashboard.domains.tags.models  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection (used for dry-run diffs)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # NullPool prevents connections from being reused across migration steps,
    # which avoids event-loop conflicts in the async context.
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
