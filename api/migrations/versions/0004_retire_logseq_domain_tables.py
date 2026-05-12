"""Retire domain tables superseded by Logseq-first architecture

Revision ID: c5e3f9a2b1d6
Revises: b7c4d2e1f8a9
Create Date: 2026-05-04

Notes, habits, recipes, grocery lists, goals, and todos are now owned by
Logseq as markdown files on the NAS. Postgres no longer needs these tables.

The logseq_index table (added in 0005) becomes the only Postgres surface for
Logseq content — a read index for AI queries, not a source of truth.

Downgrade is intentionally a no-op: DROP TABLE is irreversible without a
database backup. To restore, recover from a pre-migration database snapshot.

NOTE: Made defensive for clean-install compatibility — none of these tables
exist on a fresh DB (they were created by the raw-SQL 0001 baseline, which
is not tracked by Alembic). All operations are no-ops on a fresh install.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e3f9a2b1d6"
down_revision: Union[str, None] = "b7c4d2e1f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def _constraint_exists(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = :t AND constraint_name = :c"
        ),
        {"t": table, "c": constraint},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Detach kept tables from retired tables ────────────────────────────────
    # calendar_events is kept but carries FK columns referencing todos and goals.
    # Drop the constraints and columns first so the table drops below succeed.
    if _table_exists(conn, "calendar_events"):
        if _constraint_exists(conn, "calendar_events", "calendar_events_todo_id_fkey"):
            op.drop_constraint("calendar_events_todo_id_fkey", "calendar_events", type_="foreignkey")
        if _has_column(conn, "calendar_events", "todo_id"):
            op.drop_column("calendar_events", "todo_id")
        if _constraint_exists(conn, "calendar_events", "calendar_events_goal_id_fkey"):
            op.drop_constraint("calendar_events_goal_id_fkey", "calendar_events", type_="foreignkey")
        if _has_column(conn, "calendar_events", "goal_id"):
            op.drop_column("calendar_events", "goal_id")

    # ── Leaf tables (their FKs point into tables dropped further below) ───────

    # note_links.source_note_id → notes.id  (must precede notes)
    if _table_exists(conn, "note_links"):
        op.drop_table("note_links")

    # habit_occurrences.habit_id → habits.id  (must precede habits)
    # habit_occurrences.todo_id  → todos.id   (must precede todos)
    if _table_exists(conn, "habit_occurrences"):
        op.drop_table("habit_occurrences")

    # grocery_items.list_id              → grocery_lists.id      (must precede grocery_lists)
    # grocery_items.recipe_id            → recipes.id            (must precede recipes)
    # grocery_items.recipe_ingredient_id → recipe_ingredients.id (must precede recipe_ingredients)
    if _table_exists(conn, "grocery_items"):
        op.drop_table("grocery_items")

    # recipe_steps.recipe_id → recipes.id  (must precede recipes)
    if _table_exists(conn, "recipe_steps"):
        op.drop_table("recipe_steps")

    # recipe_ingredients.recipe_id → recipes.id  (must precede recipes)
    if _table_exists(conn, "recipe_ingredients"):
        op.drop_table("recipe_ingredients")

    # ── Mid-tier tables ───────────────────────────────────────────────────────

    # grocery_lists.todo_id → todos.id  (must precede todos)
    if _table_exists(conn, "grocery_lists"):
        op.drop_table("grocery_lists")

    # recipes.notes_id → notes.id   (must precede notes)
    # recipes.goal_id  → goals.id   (must precede goals)
    if _table_exists(conn, "recipes"):
        op.drop_table("recipes")

    # habits.goal_id → goals.id  (must precede goals)
    if _table_exists(conn, "habits"):
        op.drop_table("habits")

    # ── Root tables ───────────────────────────────────────────────────────────

    # PG drops triggers automatically with the table, but being explicit here
    # documents the dependency and ensures idempotency on partial re-runs.
    if _table_exists(conn, "notes"):
        # note_backlinks and note_tags have FKs → notes; must precede notes drop.
        # These tables exist when the DB was initialized via Phase-0 raw SQL (pre-Alembic)
        # or when migration 0010 already ran. Guard with _table_exists for idempotency.
        if _table_exists(conn, "note_backlinks"):
            op.drop_table("note_backlinks")
        if _table_exists(conn, "note_tags"):
            op.drop_table("note_tags")
        op.execute("DROP TRIGGER IF EXISTS notes_updated_at ON notes")
        op.drop_table("notes")

    # todos.goal_id → goals.id  (must precede goals)
    if _table_exists(conn, "todos"):
        op.execute("DROP TRIGGER IF EXISTS todos_updated_at ON todos")
        op.drop_table("todos")

    if _table_exists(conn, "goals"):
        op.execute("DROP TRIGGER IF EXISTS goals_updated_at ON goals")
        op.drop_table("goals")

    # ── Enums that exclusively served the retired tables ──────────────────────
    # note_type     → notes.type
    # priority_level → goals.priority, todos.priority
    op.execute("DROP TYPE IF EXISTS note_type")
    op.execute("DROP TYPE IF EXISTS priority_level")


def downgrade() -> None:
    # Intentional no-op: DROP TABLE is irreversible without a database backup.
    # These tables have been retired in favour of Logseq markdown files on the
    # NAS. To restore, recover from a pre-migration database snapshot.
    pass
