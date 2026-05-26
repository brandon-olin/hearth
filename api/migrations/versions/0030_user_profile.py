"""Phase 1 of AI coach redesign — user profile bootstrap + proposed-diffs workflow.

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-25

This migration is the first concrete step of the AI coach redesign documented
in docs/ai-coach-redesign.md. It does NOT introduce a new profile table —
member_ai_memory.memory_text is already a per-user curated text blob, written
silently today by the chat memory-refresh pass. The redesign treats memory_text
as the *user profile* (read by both coach and chatbot) and adds an
accept/reject workflow on top so the AI no longer overwrites the profile
silently.

Two changes:

1. Adds last_bootstrapped_at to member_ai_memory.
   - NULL means the richer bootstrap pass (reads notes/documents + behavioural
     data) has never run for this user.
   - Distinct from last_updated_at, which advances on any accepted change
     (user edit, accepted proposal, or legacy silent refresh).

2. Creates user_profile_updates.
   - One row per proposed change to the profile (from bootstrap or, later,
     incremental passes).
   - User accepts → proposed_content_md overwrites member_ai_memory.memory_text.
   - User rejects → status flips, profile is unchanged.
   - source: "bootstrap" | "incremental" | "manual"
   - status: "pending" | "accepted" | "rejected" | "superseded"
"""

from alembic import op
import sqlalchemy as sa


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema on restart

    # 1) Add last_bootstrapped_at to member_ai_memory.
    op.add_column(
        "member_ai_memory",
        sa.Column("last_bootstrapped_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2) Create user_profile_updates.
    op.create_table(
        "user_profile_updates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("proposed_content_md", sa.Text(), nullable=False),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="incremental",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Drop the server defaults so future writes are explicit at the
    # application layer (matches the convention used by other migrations
    # such as 0029_category_notify_threshold).
    op.alter_column("user_profile_updates", "source", server_default=None)
    op.alter_column("user_profile_updates", "status", server_default=None)

    # Index used by the "list pending updates" query.
    op.create_index(
        "ix_user_profile_updates_user_status",
        "user_profile_updates",
        ["user_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_index("ix_user_profile_updates_user_status", table_name="user_profile_updates")
    op.drop_table("user_profile_updates")
    op.drop_column("member_ai_memory", "last_bootstrapped_at")
