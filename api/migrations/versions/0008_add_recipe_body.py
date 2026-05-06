"""add recipe body jsonb

Revision ID: 0008
Revises: f1c8b3e6a9d2
Create Date: 2026-05-06

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "f1c8b3e6a9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("body", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "body")
