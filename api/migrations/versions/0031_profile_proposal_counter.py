"""Phase 1.5 of AI coach redesign — notes-driven profile proposer counter.

Revision ID: 0031
Revises: 0030
Create Date: 2026-05-25

Adds a notes_at_last_proposal counter to member_ai_memory so the
notes-driven incremental proposer (profile_service.maybe_propose_from_notes)
can decide whether enough new note activity has accumulated to justify
asking the AI to draft a proposed profile update.

Counter advances every time the proposer runs, regardless of outcome
(produced a proposal, skipped silently, or errored) — so a single user can
never trigger more than one proposer call per N new notes.
"""

from alembic import op
import sqlalchemy as sa


revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema on restart

    # Using IF NOT EXISTS so this is a safe no-op if 0029b already created it.
    op.execute(sa.text(
        "ALTER TABLE member_ai_memory "
        "ADD COLUMN IF NOT EXISTS notes_at_last_proposal integer NOT NULL DEFAULT 0"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_column("member_ai_memory", "notes_at_last_proposal")
