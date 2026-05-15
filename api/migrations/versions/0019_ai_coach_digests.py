"""Add ai_coach_digests table

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-13

Stores morning and evening AI coach digests for each user.
One row per (user_id, date, kind) — enforced by the unique index.
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_coach_digests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        # 'morning' or 'evening'
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # Tone used when the digest was generated — stored for display / auditing.
        sa.Column("tone", sa.String(50), nullable=False, server_default="supportive"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # One digest per user per day per session type.
    op.create_index(
        "ix_ai_coach_digests_user_date_kind",
        "ai_coach_digests",
        ["user_id", "date", "kind"],
        unique=True,
    )
    # Fast lookup of all digests for a user ordered by date.
    op.create_index(
        "ix_ai_coach_digests_user_date",
        "ai_coach_digests",
        ["user_id", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_coach_digests_user_date")
    op.drop_index("ix_ai_coach_digests_user_date_kind")
    op.drop_table("ai_coach_digests")
