"""add ai_usage table for per-user token tracking

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-11

Adds the ai_usage table.  One row is written after each completed AI API call
so that token consumption can be monitored per user over time.  The table is
intentionally simple at this stage — no quota enforcement yet, just recording.

Columns:
  id                UUID PK
  user_id           FK → users (CASCADE delete)
  conversation_id   FK → ai_conversations (SET NULL on delete) — nullable
  input_tokens      INTEGER
  output_tokens     INTEGER
  model             TEXT  — exact model string from the provider response
  turn_kind         TEXT  — "chat" | "memory_refresh"
  created_at        TIMESTAMPTZ

Indexes:
  ix_ai_usage_user_created  (user_id, created_at)  — used by monthly rollups
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": name},
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
    if not _table_exists(conn, "ai_usage"):
        # conversation_id FK is only added when ai_conversations exists.
        # On a fresh install that table may not exist yet; the column is
        # nullable so omitting the FK constraint is safe — the FK can be
        # added retroactively once ai_conversations is created.
        has_conversations = _table_exists(conn, "ai_conversations")
        conversation_id_col = sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_conversations.id", ondelete="SET NULL") if has_conversations else None,
            nullable=True,
        )

        op.create_table(
            "ai_usage",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            conversation_id_col,
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("turn_kind", sa.Text(), nullable=False, server_default="'chat'"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        if not _index_exists(conn, "ix_ai_usage_user_created"):
            op.create_index(
                "ix_ai_usage_user_created",
                "ai_usage",
                ["user_id", "created_at"],
            )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_user_created", table_name="ai_usage")
    op.drop_table("ai_usage")
