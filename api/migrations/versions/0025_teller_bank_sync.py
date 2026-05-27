"""Add Teller bank-sync columns to budget_accounts

Revision ID: 0025
Revises: 0024b
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
down_revision = "0024b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Columns already created by 0024b_budget_domain on fresh Postgres deployments.
    # Using ADD COLUMN IF NOT EXISTS so this is a safe no-op in that case, while
    # still applying correctly on any older deployment that ran migrations before
    # 0024b existed.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    for col_sql in [
        "ALTER TABLE budget_accounts ADD COLUMN IF NOT EXISTS teller_enrollment_id varchar(200)",
        "ALTER TABLE budget_accounts ADD COLUMN IF NOT EXISTS teller_access_token text",
        "ALTER TABLE budget_accounts ADD COLUMN IF NOT EXISTS teller_account_id varchar(200)",
        "ALTER TABLE budget_accounts ADD COLUMN IF NOT EXISTS teller_institution_name varchar(200)",
        "ALTER TABLE budget_accounts ADD COLUMN IF NOT EXISTS teller_last_synced_at timestamptz",
        "ALTER TABLE budget_accounts ADD COLUMN IF NOT EXISTS teller_cursor varchar(200)",
    ]:
        op.execute(sa.text(col_sql))


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
