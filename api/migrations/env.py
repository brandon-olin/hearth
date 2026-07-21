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
import life_dashboard.ai.models  # noqa: F401
import life_dashboard.audit.models  # noqa: F401
import life_dashboard.domains.calendar_events.models  # noqa: F401
import life_dashboard.domains.contacts.models  # noqa: F401
import life_dashboard.domains.documents.models  # noqa: F401
import life_dashboard.domains.goals.models  # noqa: F401
import life_dashboard.domains.grocery_lists.models  # noqa: F401
import life_dashboard.domains.habits.models  # noqa: F401
import life_dashboard.domains.notes.models  # noqa: F401
import life_dashboard.domains.projects.models  # noqa: F401
import life_dashboard.domains.recipes.models  # noqa: F401
import life_dashboard.domains.tags.models  # noqa: F401
import life_dashboard.domains.todos.models  # noqa: F401
import life_dashboard.domains.workouts.models  # noqa: F401
import life_dashboard.domains.collections.models  # noqa: F401
import life_dashboard.domains.templates.models  # noqa: F401
import life_dashboard.proposals.models  # noqa: F401
import life_dashboard.webhooks.models  # noqa: F401

target_metadata = Base.metadata


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


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
    # render_as_batch rebuilds the table (create/copy/drop/rename) for ALTERs
    # SQLite cannot express directly — dropping columns, adding constraints,
    # changing types. Postgres does not need it and is left untouched.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=_is_sqlite(),
    )
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
    # Both engines run migrations (ADR-014). A fresh SQLite DB is built by
    # create_all() and stamped at head on first boot, so historical revisions
    # 0001-0045 never replay there — only new revisions run, in batch mode.
    if _is_sqlite():
        print(
            "[alembic] SQLite detected — running migrations in batch mode.\n"
            "Fresh databases are created via create_all() and stamped at head "
            "on first boot; only newer revisions are applied."
        )
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
