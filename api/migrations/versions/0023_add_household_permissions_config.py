"""Add permissions_config to households table

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-14

Changes:
  - Add `permissions_config` JSON column to `households` (nullable, defaults to NULL)
    NULL means "use application-level defaults" (no custom config set).
"""

from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "households",
        sa.Column("permissions_config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite doesn't support DROP COLUMN in older versions — skip.
        return
    op.drop_column("households", "permissions_config")
