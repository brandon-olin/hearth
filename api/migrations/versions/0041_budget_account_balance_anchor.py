"""Add balance anchor fields to budget_accounts for running balance computation.

Revision ID: 0041
Revises: 0040
Create Date: 2026-06-03

scheduler-001: weekly Teller balance API call sets an anchor
(balance_at_last_sync + balance_synced_at).  Between weekly syncs,
current_balance is computed as anchor + SUM of transactions imported after
balance_synced_at, giving a live running balance without calling the
Teller balance endpoint on every transaction sync.
"""

from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "budget_accounts",
        sa.Column("balance_at_last_sync", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "budget_accounts",
        sa.Column(
            "balance_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("budget_accounts", "balance_synced_at")
    op.drop_column("budget_accounts", "balance_at_last_sync")
