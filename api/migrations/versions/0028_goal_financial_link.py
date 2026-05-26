"""Add financial_link JSONB to goals

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-22

Stores an optional structured link between a Goal and a budget entity so
the app can derive live progress and keep the two in sync.

Shape examples
--------------
Spending cap (syncs with BudgetCategory.default_monthly_amount):
  { "type": "spending_cap", "category_id": "<uuid>", "monthly_limit": 500 }

Savings target (tracks progress against BudgetAccount.current_balance):
  { "type": "savings_target", "account_id": "<uuid>", "target_amount": 10000 }

Debt payoff:
  { "type": "debt_payoff", "account_id": "<uuid>", "target_balance": 0 }
"""

from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite: handled by _patch_sqlite_schema on restart

    op.add_column(
        "goals",
        sa.Column("financial_link", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.drop_column("goals", "financial_link")
