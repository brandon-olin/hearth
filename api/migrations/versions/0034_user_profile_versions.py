"""Phase 4 of AI coach redesign — user_profile_versions append-only history.

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-25

Phase 4 adds three connected capabilities: profile versioning, a weekly
scheduled refresh, and a decay pass. The versioning piece is the
foundation — every time member_ai_memory.memory_text is written (by
bootstrap, the incremental proposer, the update_profile tool, the
scheduled refresh, or a direct admin PATCH), we snapshot the PREVIOUS
content into user_profile_versions. That gives us:

  - A safety net (can roll back if the AI does something weird)
  - Debuggability (Brandon can inspect how the profile evolved)
  - A history surface to power future "show me how I've changed" features

Bounded retention is enforced in the application layer (last ~50 rows
per user) rather than at the DB level — keeps the migration simple
and lets us tune the cap without a schema change.

source values (must match profile_service constants):
  "bootstrap"   — initial bootstrap on key save
  "incremental" — notes-driven background proposer
  "manual"      — chat-driven update_profile tool call
  "scheduled"   — Phase 4 weekly refresh
  "direct_edit" — admin/debug PATCH /ai/profile
"""

from alembic import op
import sqlalchemy as sa


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema on restart

    op.create_table(
        "user_profile_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The previous content_md, captured before being overwritten.
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_user_profile_versions_user_created",
        "user_profile_versions",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_index(
        "ix_user_profile_versions_user_created",
        table_name="user_profile_versions",
    )
    op.drop_table("user_profile_versions")
