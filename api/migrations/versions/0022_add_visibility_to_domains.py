"""Add visibility columns to all shareable domain tables

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-14

Changes:
  - Add `visibility` VARCHAR(20) NOT NULL to 9 tables, with per-domain defaults:
      household (default): todos, projects, grocery_lists, recipes
      personal  (default): notes, documents, workouts, habits, goals
  - Add `shared_with_user_ids` JSON (nullable) to the same 9 tables.
    Only populated when visibility = 'members'; stores a JSON array of user-id
    strings for the specifically-shared users.

Visibility semantics:
  household  → all members of the household can see the item
  personal   → only the creating user can see the item
  members    → the creator + any user whose ID appears in shared_with_user_ids

SQLite note:
  This migration is skipped for SQLite (the app uses create_all() instead).
  If you are running the dev SQLite instance you must run the following
  ALTER TABLE statements manually via `sqlite3 ./life_dashboard.db`:

    ALTER TABLE todos          ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'household';
    ALTER TABLE todos          ADD COLUMN shared_with_user_ids JSON;
    ALTER TABLE projects       ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'household';
    ALTER TABLE projects       ADD COLUMN shared_with_user_ids JSON;
    ALTER TABLE grocery_lists  ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'household';
    ALTER TABLE grocery_lists  ADD COLUMN shared_with_user_ids JSON;
    ALTER TABLE recipes        ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'household';
    ALTER TABLE recipes        ADD COLUMN shared_with_user_ids JSON;
    ALTER TABLE notes          ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'personal';
    ALTER TABLE notes          ADD COLUMN shared_with_user_ids JSON;
    ALTER TABLE documents      ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'personal';
    ALTER TABLE documents      ADD COLUMN shared_with_user_ids JSON;
    ALTER TABLE workouts       ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'personal';
    ALTER TABLE workouts       ADD COLUMN shared_with_user_ids JSON;
    ALTER TABLE habits         ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'personal';
    ALTER TABLE habits         ADD COLUMN shared_with_user_ids JSON;
    ALTER TABLE goals          ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'personal';
    ALTER TABLE goals          ADD COLUMN shared_with_user_ids JSON;
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


# ── Per-table visibility defaults ─────────────────────────────────────────────

HOUSEHOLD_TABLES = ["todos", "projects", "grocery_lists", "recipes"]
PERSONAL_TABLES  = ["notes", "documents", "workouts", "habits", "goals"]


def upgrade() -> None:
    # Detect SQLite — create_all() handles schema there, skip migration body.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    for table in HOUSEHOLD_TABLES:
        op.add_column(
            table,
            sa.Column(
                "visibility",
                sa.String(20),
                nullable=False,
                server_default="household",
            ),
        )
        op.add_column(
            table,
            sa.Column("shared_with_user_ids", sa.JSON(), nullable=True),
        )

    for table in PERSONAL_TABLES:
        op.add_column(
            table,
            sa.Column(
                "visibility",
                sa.String(20),
                nullable=False,
                server_default="personal",
            ),
        )
        op.add_column(
            table,
            sa.Column("shared_with_user_ids", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    for table in HOUSEHOLD_TABLES + PERSONAL_TABLES:
        op.drop_column(table, "shared_with_user_ids")
        op.drop_column(table, "visibility")
