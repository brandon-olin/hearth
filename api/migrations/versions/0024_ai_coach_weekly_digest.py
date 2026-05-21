"""Add weekly kind to ai_coach_digests and document scheduler changes

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-20

No schema changes are required — the kind column is VARCHAR(20) with no
CHECK constraint, so 'weekly' is a valid value already.

This migration is a marker for the feature addition:
  - New CoachDigestKind.weekly enum value
  - Friday 17:00 scheduled job in main.py
  - Historical completion context (_fetch_history) in coach_service.py
  - Morning schedule moved from 02:00 → 07:00
  - Evening schedule moved from 20:00 → 17:30

If you need to downgrade, simply remove the weekly rows:
  DELETE FROM ai_coach_digests WHERE kind = 'weekly';
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No DDL needed — VARCHAR(20) already accepts 'weekly'.
    pass


def downgrade() -> None:
    op.execute("DELETE FROM ai_coach_digests WHERE kind = 'weekly'")
