"""ai-access-001 — per-member AI features gating.

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-25

Adds an admin-controlled toggle to HouseholdMembership that determines
whether a household member has access to AI features (coach, chat,
journal, profile-driven personalisation). Defaults to True so existing
members are unaffected.

The product context for this is families — Hearth is designed for
households where adults and kids share the same install. Admins
(owners or other admins) need a way to disable AI features for
members who shouldn't have access yet (typically kids), without
deleting the member or revoking other features.

Cross-cuts: every /ai/* endpoint checks this flag via a new
require_ai_enabled dependency. When false, the API returns 403 and
the frontend hides AI surfaces (coach widget, chat sidebar, journal
button, AI settings section).

Existing AI data (profile, journal_signals, audit logs) is NOT
deleted when the flag flips — disabling is a posture toggle, not an
erasure. If the admin re-enables later, history is intact.
"""

from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema on restart

    op.add_column(
        "household_memberships",
        sa.Column(
            "ai_features_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column(
        "household_memberships", "ai_features_enabled", server_default=None
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_column("household_memberships", "ai_features_enabled")
