"""add cover_image_url column to recipes

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-08

The Recipe model has a `cover_image_url` text field that was never
included in the original migration that created the recipes table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("cover_image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "cover_image_url")
