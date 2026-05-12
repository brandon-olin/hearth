"""Add assigned_to_user_id to todos

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-11

The todos table was created in 0006 without an assignee column.
The SQLAlchemy model always had assigned_to_user_id; this migration
closes the gap so INSERTs stop failing with UndefinedColumnError.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0016"
down_revision = "0015"
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


def _index_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "todos", "assigned_to_user_id"):
        op.add_column(
            "todos",
            sa.Column(
                "assigned_to_user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    if not _index_exists(conn, "ix_todos_assigned_to_user_id"):
        op.create_index(
            "ix_todos_assigned_to_user_id", "todos", ["assigned_to_user_id"]
        )


def downgrade() -> None:
    op.drop_index("ix_todos_assigned_to_user_id", table_name="todos")
    op.drop_column("todos", "assigned_to_user_id")
