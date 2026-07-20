"""Replace native Postgres enum types with VARCHAR + CHECK.

Revision ID: 0047
Revises: 0046
Create Date: 2026-07-20

ADR-015 (`plans/015-enum-drift-reconciliation.md`). Seven columns are native
Postgres enums in the migration history while the ORM models declare
`SaEnum(..., native_enum=False)` — VARCHAR + CHECK. A `create_all()`-built
database therefore has a *different column type* than production, which replays
migrations. Migration 0046 shipped broken through exactly that gap: it compared
`collections.domain` against a VARCHAR bind and failed the Railway pre-deploy
with `operator does not exist: collection_domain = character varying`.

This converts the database to match the models. The models are already correct
and are not touched.

Mechanics worth knowing:

- Postgres refuses `ALTER COLUMN ... TYPE` while a DEFAULT is attached, so the
  three columns carrying one need the default dropped and re-added around the
  change. The re-added default is a plain string literal; after the type change
  it is a varchar default rather than `'page'::document_kind`.
- `USING col::text` is a total conversion — every existing label maps to its
  own text, so no value can be lost. This is what makes the migration safe
  against live household data.
- `priority_level` backs BOTH `goals.priority` and `todos.priority`. Types are
  dropped only after every column is converted, so the shared type does not
  get dropped out from under the second column.
- VARCHAR lengths match what `SaEnum(native_enum=False)` generates for the same
  labels (the longest label), so `create_all` and this migration agree.
- CHECK constraints are NULL-permissive by construction: `NULL IN (...)`
  evaluates to NULL, not FALSE, so a CHECK passes on NULL rows. The two
  nullable columns (`goals.priority`, `todos.priority`) keep working.

Idempotency: the conversion is guarded on the column still being USER-DEFINED,
so re-running is a no-op. `DROP TYPE IF EXISTS` and the constraint drop before
each add make the rest re-runnable too.
"""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


# (table, column, type_name, values, server_default)
_ENUM_COLUMNS = [
    ("collections", "domain", "collection_domain", ("notes", "documents"), None),
    ("documents", "kind", "document_kind", ("page", "template"), "page"),
    (
        "exercise_entries",
        "type",
        "exercise_type",
        ("strength", "cardio", "hiit", "flexibility", "other"),
        None,
    ),
    ("goals", "priority", "priority_level", ("low", "medium", "high"), None),
    (
        "household_memberships",
        "role",
        "membership_role",
        ("owner", "admin", "member", "viewer", "agent"),
        "member",
    ),
    (
        "projects",
        "status",
        "project_status",
        ("backlog", "active", "on_deck", "in_progress", "complete", "archived"),
        "active",
    ),
    ("todos", "priority", "priority_level", ("low", "medium", "high"), None),
]

# Dropped only after every column above is converted — priority_level backs two.
_TYPES_TO_DROP = [
    "collection_domain",
    "document_kind",
    "exercise_type",
    "membership_role",
    "project_status",
    "priority_level",
]

# Types whose columns vanished when later migrations recreated their tables
# (0010 rebuilt notes, 0044 rebuilt audit_log). Harmless if already absent.
_ORPHANED_TYPES = ["note_kind", "actor_type"]


def _is_user_defined(bind, table: str, column: str) -> bool:
    """True when the column is still a native enum, so the work is pending."""
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t "
                "AND column_name = :c AND data_type = 'USER-DEFINED'"
            ),
            {"t": table, "c": column},
        ).scalar()
    )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # SQLite already stores these as VARCHAR — create_all() builds the
        # tier and the models declare native_enum=False — so there is no type
        # to convert. The CHECK constraints are still added, so that a SQLite
        # database created before this revision ends up matching one created
        # after it. Not a skipped step; a smaller amount of real work.
        for table, column, type_name, values, _default in _ENUM_COLUMNS:
            allowed = ", ".join(f"'{v}'" for v in values)
            with op.batch_alter_table(table) as batch_op:
                batch_op.create_check_constraint(type_name, f"{column} IN ({allowed})")
        return

    for table, column, type_name, values, default in _ENUM_COLUMNS:
        if not _is_user_defined(bind, table, column):
            continue  # already converted; re-run is a no-op

        length = max(len(v) for v in values)

        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")

        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE varchar({length}) USING {column}::text"
        )

        if default is not None:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'"
            )

        # Named for the enum type it replaces, because that is exactly what
        # SQLAlchemy names the constraint for
        # `SaEnum(..., name="<type>", create_constraint=True)` — so create_all
        # and this migration produce byte-identical schemas.
        allowed = ", ".join(f"'{v}'" for v in values)
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {type_name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {type_name} "
            f"CHECK ({column} IN ({allowed}))"
        )

    # Safe now that no column references them. Without CASCADE, so a lingering
    # dependency raises rather than silently dropping someone else's column.
    for type_name in _TYPES_TO_DROP + _ORPHANED_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {type_name}")


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        for table, _column, type_name, _values, _default in _ENUM_COLUMNS:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(type_name, type_="check")
        return

    # Recreate each type once, then convert the columns back.
    seen: set[str] = set()
    for _table, _column, type_name, values, _default in _ENUM_COLUMNS:
        if type_name in seen:
            continue
        seen.add(type_name)
        labels = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {type_name} AS ENUM ({labels})")

    for table, column, type_name, _values, default in _ENUM_COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {type_name}")
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE {type_name} USING {column}::{type_name}"
        )
        if default is not None:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"SET DEFAULT '{default}'::{type_name}"
            )
