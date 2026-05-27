"""Add is_income flag to budget_category_groups.

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-25

Adds a boolean is_income column to budget_category_groups.
When true, all positive transactions in any category belonging to this group
are counted as income in analytics and summary queries — regardless of what
the group is named.  This replaces the previous hardcoded name == "income"
check so users can name their income group anything they like (Salary, Inflows, etc.).

Backfill: any existing group whose name lowercases to "income" is set to true.
SQLite is handled inline (ADD COLUMN is supported; we skip the Alembic op and
use a raw statement instead to avoid the dialect incompatibility).
"""

from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        # SQLite supports ADD COLUMN; use raw SQL to avoid Alembic dialect issues.
        # Wrapped in try/except so re-running the migration is safe.
        try:
            bind.execute(sa.text(
                "ALTER TABLE budget_category_groups "
                "ADD COLUMN is_income INTEGER NOT NULL DEFAULT 0"
            ))
        except Exception:
            pass  # Column already exists — idempotent
    else:
        op.execute(sa.text(
            "ALTER TABLE budget_category_groups "
            "ADD COLUMN IF NOT EXISTS is_income boolean NOT NULL DEFAULT false"
        ))

    # Backfill: mark any group currently named "income" (case-insensitive).
    # Runs on both dialects — covers users who had an "Income" group before
    # this flag existed.
    # SQLite stores booleans as integers (1/0); Postgres requires the boolean
    # literal true. Use a dialect-aware value to satisfy both.
    true_val = "1" if bind.dialect.name == "sqlite" else "true"
    op.execute(
        sa.text(
            f"UPDATE budget_category_groups "
            f"SET is_income = {true_val} "
            f"WHERE lower(name) = 'income'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite doesn't support DROP COLUMN
    op.drop_column("budget_category_groups", "is_income")
