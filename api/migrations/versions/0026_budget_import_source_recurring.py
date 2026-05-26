"""Add 'recurring' to budget_transactions import_source CHECK constraint

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-22

SQLite note: this migration is a no-op on SQLite.
The recurring/generate endpoint uses import_source=NULL for generated instances
(recurring_template_id IS NOT NULL already identifies them), so the CHECK
constraint never needs to accept 'recurring' on the SQLite dev path.

On Postgres the constraint must be updated before any code that writes
import_source='recurring' is deployed.  Currently the service writes NULL, but
adding 'recurring' here future-proofs the constraint for analytics queries that
may filter on import_source='recurring' later.
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return  # SQLite path uses NULL; no constraint change needed

    # Drop the old CHECK constraint and recreate it with 'recurring' added.
    # SQLAlchemy names the constraint after the enum's `name` parameter.
    op.execute(
        "ALTER TABLE budget_transactions "
        "DROP CONSTRAINT IF EXISTS ck_budget_transactions_budget_import_source"
    )
    op.execute(
        "ALTER TABLE budget_transactions ADD CONSTRAINT "
        "ck_budget_transactions_budget_import_source "
        "CHECK (import_source IN ('csv', 'ofx', 'manual', 'teller', 'plaid', 'recurring'))"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    op.execute(
        "ALTER TABLE budget_transactions "
        "DROP CONSTRAINT IF EXISTS ck_budget_transactions_budget_import_source"
    )
    op.execute(
        "ALTER TABLE budget_transactions ADD CONSTRAINT "
        "ck_budget_transactions_budget_import_source "
        "CHECK (import_source IN ('csv', 'ofx', 'manual', 'teller', 'plaid'))"
    )
