"""Add Teller bank-sync columns to budget_accounts

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-22

Changes:
  - teller_enrollment_id  VARCHAR(200) NULL
  - teller_access_token   TEXT         NULL
  - teller_account_id     VARCHAR(200) NULL
  - teller_institution_name VARCHAR(200) NULL
  - teller_last_synced_at TIMESTAMPTZ  NULL
  - teller_cursor         VARCHAR(200) NULL

These columns store per-account Teller connection state so the API can
poll Teller for new transactions without requiring a webhook endpoint.
The access token is stored as plain text (no encryption) in V1; an
encrypted-at-rest path is planned for the cloud-hosted tier.
"""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_accounts", sa.Column("teller_enrollment_id", sa.String(200), nullable=True))
    op.add_column("budget_accounts", sa.Column("teller_access_token", sa.Text(), nullable=True))
    op.add_column("budget_accounts", sa.Column("teller_account_id", sa.String(200), nullable=True))
    op.add_column("budget_accounts", sa.Column("teller_institution_name", sa.String(200), nullable=True))
    op.add_column("budget_accounts", sa.Column("teller_last_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("budget_accounts", sa.Column("teller_cursor", sa.String(200), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite DROP COLUMN not supported in older versions
    op.drop_column("budget_accounts", "teller_cursor")
    op.drop_column("budget_accounts", "teller_last_synced_at")
    op.drop_column("budget_accounts", "teller_institution_name")
    op.drop_column("budget_accounts", "teller_account_id")
    op.drop_column("budget_accounts", "teller_access_token")
    op.drop_column("budget_accounts", "teller_enrollment_id")
