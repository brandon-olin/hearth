"""add icon column to documents

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-07

The Document model has an `icon` text field (stores an emoji or icon
identifier for the page, matching the Notion import format) that was
never included in the 0007 migration that created the documents table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("icon", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "icon")
