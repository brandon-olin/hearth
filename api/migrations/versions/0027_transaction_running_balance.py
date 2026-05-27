"""Add running_balance to budget_transactions

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-22

Stores the account balance reported by the bank at the time of each
transaction (sourced from Teller's running_balance field).  NULL for
transactions imported via CSV/OFX or created manually.  Used for
balance-over-time charts on savings accounts and future "projected
balance" features on checking accounts.
"""

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite: column added via create_all() / _patch_sqlite_schema() on restart
        return

    op.execute(sa.text(
        "ALTER TABLE budget_transactions ADD COLUMN IF NOT EXISTS running_balance numeric(14,2)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_column("budget_transactions", "running_balance")
