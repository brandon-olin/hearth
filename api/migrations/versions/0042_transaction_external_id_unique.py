"""Enforce per-account uniqueness of budget_transactions.external_id.

Revision ID: 0042
Revises: 0041
Create Date: 2026-07-07

Audit #13 / plan 011: import dedup was application-level only
(bulk_import_transactions loads existing external_id/dedup_hash into Python
sets, then skips matches). Two overlapping syncs both read the same snapshot
and both insert — duplicate financial rows. This adds a partial unique index on
(account_id, external_id) WHERE external_id IS NOT NULL as the race-safe
backstop. Manual/CSV rows (NULL external_id) are intentionally unconstrained;
dedup_hash stays app-level only (two legit same-day identical purchases share a
hash and must both be allowed).

The upgrade fails loudly if pre-existing duplicates are present — deleting money
rows is an operator decision, not a migration side-effect.
"""

from alembic import op
import sqlalchemy as sa

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dupes = conn.execute(
        sa.text(
            """
            SELECT account_id, external_id, COUNT(*) AS n
            FROM budget_transactions
            WHERE external_id IS NOT NULL
            GROUP BY account_id, external_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if dupes:
        raise RuntimeError(
            f"Cannot add unique index: {len(dupes)} duplicated "
            "(account_id, external_id) pairs exist in budget_transactions. "
            "Resolve manually (keep one row per pair, delete/merge the rest), "
            "then re-run. Pairs: "
            + ", ".join(f"({r.account_id}, {r.external_id}) x{r.n}" for r in dupes[:20])
        )
    op.create_index(
        "uq_budget_txn_account_external_id",
        "budget_transactions",
        ["account_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
        sqlite_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_budget_txn_account_external_id", table_name="budget_transactions"
    )
