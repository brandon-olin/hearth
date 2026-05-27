"""Phase 2 of AI coach redesign — journal_signals + extraction flag.

Revision ID: 0033
Revises: 0032
Create Date: 2026-05-25

Creates the journal_signals table (one row per journal note, keyed by
note_id, holding the structured features the AI extracts at write time)
and adds the per-user ai_journal_extraction_enabled flag.

Signals captured per entry:
  sentiment           NUMERIC(3,2) in [-1.00, +1.00]
  self_talk_valence   "positive" | "neutral" | "harsh" | "mixed"
  themes              JSON array of short strings, e.g. ["consistency", "work stress"]
  notable_phrases     JSON array of short strings — used sparingly for callbacks
  energy_level        "low" | "medium" | "high" — nullable when not inferable
  entry_date          DATE — the date the entry is *about* (from the collection's
                      auto_create_rule when available, else the note's created_at).
                      Trend math anchors on this rather than created_at because a
                      user might journal about Tuesday on Wednesday morning.
  extraction_version  INTEGER — bumped when the extraction prompt changes; lets
                      us re-run extraction across rows that used an older prompt.
"""

from alembic import op
import sqlalchemy as sa


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema + create_all on restart

    op.create_table(
        "journal_signals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "note_id",
            sa.Uuid(),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("sentiment", sa.Numeric(3, 2), nullable=False),
        sa.Column(
            "self_talk_valence",
            sa.String(20),
            nullable=False,
            server_default="neutral",
        ),
        sa.Column("themes", sa.JSON(), nullable=True),
        sa.Column("notable_phrases", sa.JSON(), nullable=True),
        sa.Column("energy_level", sa.String(10), nullable=True),
        sa.Column(
            "extraction_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.alter_column("journal_signals", "self_talk_valence", server_default=None)
    op.alter_column("journal_signals", "extraction_version", server_default=None)

    # Trend queries hit (user_id, entry_date) — index it.
    op.create_index(
        "ix_journal_signals_user_entry_date",
        "journal_signals",
        ["user_id", "entry_date"],
    )

    # Per-user opt-out flag for signal extraction. Default TRUE so the
    # feature is on for new users; existing users get TRUE backfilled by
    # the server default. The application layer governs the value going
    # forward.
    # Using IF NOT EXISTS so this is a safe no-op if 0029b already created it.
    op.execute(sa.text(
        "ALTER TABLE ai_settings "
        "ADD COLUMN IF NOT EXISTS ai_journal_extraction_enabled boolean NOT NULL DEFAULT true"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_column("ai_settings", "ai_journal_extraction_enabled")
    op.drop_index(
        "ix_journal_signals_user_entry_date", table_name="journal_signals"
    )
    op.drop_table("journal_signals")
