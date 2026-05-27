"""journal-002 — check-in modes for Talk-it-out.

Revision ID: 0037
Revises: 0036b
Create Date: 2026-05-26

Adds a `mode` column to ai_conversations to record which guided
check-in the user picked when starting a journal session (or NULL if
they took the blank-slate path). Drives both the canned opening
message and a mode-specific instruction layered onto the journal
system prompt.

Valid values (enforced at the schema/API layer, not in the DB
constraint, so we can add modes without a schema migration):
  - "blank"       — no opener, default journal system prompt
  - "mood"        — short feeling-focused opener; keep it light
  - "body"        — somatic check-in opener
  - "rant"        — vent mode; system prompt tells the model to stay
                    with the user, not reality-test
  - "day_review"  — branches on local_hour at /start time:
                    morning lens (look-ahead) vs evening lens
                    (look-back). Stored as just "day_review" — the
                    branching happens at opener-generation time.

SQLite: handled by _patch_sqlite_schema on restart.
"""

from alembic import op
import sqlalchemy as sa


revision = "0037"
down_revision = "0036b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema on restart

    # Using IF NOT EXISTS so this is a safe no-op if 0029b already created it.
    op.execute(sa.text(
        "ALTER TABLE ai_conversations "
        "ADD COLUMN IF NOT EXISTS mode varchar(32)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_column("ai_conversations", "mode")
