"""Household invites, subscription tracking, and password reset tokens.

Revision ID: 0039
Revises: 0038
Create Date: 2026-05-28

Adds:
  users.force_password_change      — set True when an admin creates an account
                                     for someone; cleared once they set their own
                                     password.
  households.subscription_status   — free | trialing | active | past_due | canceled
  households.stripe_customer_id    — Stripe customer ID (cloud tier only)
  households.is_exempt             — bypasses subscription checks (dev / test accounts)
  password_reset_tokens table      — short-lived tokens for the forgot-password flow
                                     (cloud tier only, but the table exists on all tiers
                                     so the schema stays portable)
"""

from alembic import op
import sqlalchemy as sa

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        # SQLite: ADD COLUMN with simple defaults
        for stmt in [
            "ALTER TABLE users ADD COLUMN force_password_change INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE households ADD COLUMN subscription_status TEXT NOT NULL DEFAULT 'free'",
            "ALTER TABLE households ADD COLUMN stripe_customer_id TEXT",
            "ALTER TABLE households ADD COLUMN is_exempt INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                bind.execute(sa.text(stmt))
            except Exception:
                pass  # column already exists — idempotent

        try:
            bind.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id TEXT NOT NULL PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """))
        except Exception:
            pass

        return

    # ── Postgres ──────────────────────────────────────────────────────────────

    op.execute(sa.text(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS force_password_change boolean NOT NULL DEFAULT false"
    ))

    op.execute(sa.text(
        "ALTER TABLE households "
        "ADD COLUMN IF NOT EXISTS subscription_status varchar(20) NOT NULL DEFAULT 'free'"
    ))
    op.execute(sa.text(
        "ALTER TABLE households "
        "ADD COLUMN IF NOT EXISTS stripe_customer_id text"
    ))
    op.execute(sa.text(
        "ALTER TABLE households "
        "ADD COLUMN IF NOT EXISTS is_exempt boolean NOT NULL DEFAULT false"
    ))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id UUID NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user_id "
        "ON password_reset_tokens (user_id)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite doesn't support DROP COLUMN

    op.execute(sa.text("DROP TABLE IF EXISTS password_reset_tokens"))
    op.drop_column("households", "is_exempt")
    op.drop_column("households", "stripe_customer_id")
    op.drop_column("households", "subscription_status")
    op.drop_column("users", "force_password_change")
