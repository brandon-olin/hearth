"""Add link_url to todos

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-13

Adds an optional link_url column to todos so a todo can reference an
internal app page or external URL (e.g. "Get groceries" → /grocery-lists/abc).
Nullable — no existing rows are affected.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
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
    if not _column_exists(conn, "todos", "link_url"):
        op.add_column(
            "todos",
            sa.Column("link_url", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("todos", "link_url")
