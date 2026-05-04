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
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e3f9a2b1d6"
down_revision: Union[str, None] = "b7c4d2e1f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Leaf tables (their FKs point into tables dropped further below) ───────

    # note_links.source_note_id → notes.id  (must precede notes)
    op.drop_table("note_links")

    # habit_occurrences.habit_id → habits.id  (must precede habits)
    # habit_occurrences.todo_id  → todos.id   (must precede todos)
    op.drop_table("habit_occurrences")

    # grocery_items.list_id              → grocery_lists.id      (must precede grocery_lists)
    # grocery_items.recipe_id            → recipes.id            (must precede recipes)
    # grocery_items.recipe_ingredient_id → recipe_ingredients.id (must precede recipe_ingredients)
    op.drop_table("grocery_items")

    # recipe_steps.recipe_id → recipes.id  (must precede recipes)
    op.drop_table("recipe_steps")

    # recipe_ingredients.recipe_id → recipes.id  (must precede recipes)
    op.drop_table("recipe_ingredients")

    # ── Mid-tier tables ───────────────────────────────────────────────────────

    # grocery_lists.todo_id → todos.id  (must precede todos)
    op.drop_table("grocery_lists")

    # recipes.notes_id → notes.id   (must precede notes)
    # recipes.goal_id  → goals.id   (must precede goals)
    op.drop_table("recipes")

    # habits.goal_id → goals.id  (must precede goals)
    op.drop_table("habits")

    # ── Root tables ───────────────────────────────────────────────────────────

    # PG drops triggers automatically with the table, but being explicit here
    # documents the dependency and ensures idempotency on partial re-runs.
    op.execute("DROP TRIGGER IF EXISTS notes_updated_at ON notes")

    # notes.goal_id → goals.id  |  notes.todo_id → todos.id
    op.drop_table("notes")

    # todos.goal_id → goals.id  (must precede goals)
    op.drop_table("todos")

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
