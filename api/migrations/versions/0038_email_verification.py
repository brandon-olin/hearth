"""email_verification

Revision ID: 0038
Revises: 0037
Create Date: 2026-05-27

Adds:
  - users.email_verified (BOOLEAN NOT NULL)
      Backfills existing rows to TRUE so current accounts are unaffected.
      Server default is then changed to FALSE so new registrations start unverified.
  - email_verification_codes table
      Stores SHA-256 hashed 6-digit OTPs with a 15-minute expiry.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add email_verified to users ────────────────────────────────────────
    # server_default='true' backfills all existing rows as verified.
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    # Change the server default to false so new DB-level inserts start unverified.
    op.alter_column("users", "email_verified", server_default="false")

    # ── 2. Create email_verification_codes ────────────────────────────────────
    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_verification_codes_user_id",
        "email_verification_codes",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_verification_codes_user_id", table_name="email_verification_codes")
    op.drop_table("email_verification_codes")
    op.drop_column("users", "email_verified")
