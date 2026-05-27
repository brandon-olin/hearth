"""journal-001 — AiConversation.kind + note_id columns.

Revision ID: 0035
Revises: 0034b
Create Date: 2026-05-25

Adds two columns to ai_conversations so the chat infrastructure can host
guided-journal sessions alongside regular chats. journal-001 ships the
'Talk it out' surface that runs on top of the existing /ai/chat streaming
endpoint — the only thing that differs is the system prompt and the
restricted tool set, both decided by `kind`.

Columns:
  kind     VARCHAR(20) NOT NULL DEFAULT 'chat'
           — "chat" (default) or "journal"
  note_id  UUID NULL FK→notes ON DELETE SET NULL
           — for kind='journal', points at the journal entry the
             session is filling in (today's note in the user's
             journal-kind collection). NULL for kind='chat'.

One journal conversation per (user, note_id) — the journal endpoint
resolves the existing conversation when re-opening Talk-it-out for the
same day's entry. New day = new note = new conversation.
"""

from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema on restart

    op.add_column(
        "ai_conversations",
        sa.Column("kind", sa.String(20), nullable=False, server_default="chat"),
    )
    op.alter_column("ai_conversations", "kind", server_default=None)

    op.add_column(
        "ai_conversations",
        sa.Column(
            "note_id",
            sa.Uuid(),
            sa.ForeignKey("notes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Look-up index for "find this user's existing journal session for this note".
    op.create_index(
        "ix_ai_conversations_user_kind_note",
        "ai_conversations",
        ["user_id", "kind", "note_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_index(
        "ix_ai_conversations_user_kind_note", table_name="ai_conversations"
    )
    op.drop_column("ai_conversations", "note_id")
    op.drop_column("ai_conversations", "kind")
