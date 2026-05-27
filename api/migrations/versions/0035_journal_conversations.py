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

    # Using IF NOT EXISTS so these are safe no-ops if 0029b already created the columns.
    op.execute(sa.text(
        "ALTER TABLE ai_conversations "
        "ADD COLUMN IF NOT EXISTS kind varchar(20) NOT NULL DEFAULT 'chat'"
    ))
    op.execute(sa.text(
        "ALTER TABLE ai_conversations "
        "ADD COLUMN IF NOT EXISTS note_id uuid REFERENCES notes(id) ON DELETE SET NULL"
    ))

    # Look-up index for "find this user's existing journal session for this note".
    # Wrapped in a DO block so it's idempotent.
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_ai_conversations_user_kind_note "
        "ON ai_conversations (user_id, kind, note_id)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_index(
        "ix_ai_conversations_user_kind_note", table_name="ai_conversations"
    )
    op.drop_column("ai_conversations", "note_id")
    op.drop_column("ai_conversations", "kind")
