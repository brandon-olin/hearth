"""Add notify_threshold_pct to budget_categories

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-22

Adds an optional integer column to budget_categories that controls when
budget-threshold notifications fire for that category.

  NULL  — notifications are disabled for this category
  80    — notify at 80% (and again at 100%); the default when enabled
  <n>   — notify at n% (and again at 100%)

The column is added with a server-side default of 80 so existing
categories inherit sensible behaviour without requiring a data migration.
Users can override per-category on the categories settings page.
"""

from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema on restart

    op.execute(sa.text(
        "ALTER TABLE budget_categories ADD COLUMN IF NOT EXISTS notify_threshold_pct integer"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_column("budget_categories", "notify_threshold_pct")
