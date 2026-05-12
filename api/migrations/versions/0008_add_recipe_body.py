"""add recipe body jsonb

Revision ID: 0008
Revises: f1c8b3e6a9d2
Create Date: 2026-05-06

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "f1c8b3e6a9d2"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "recipes", "body"):
        op.add_column("recipes", sa.Column("body", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("recipes", "body")
