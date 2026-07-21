"""Add demo_data_records — the sample-data manifest.

Revision ID: 0052
Revises: 0051
Create Date: 2026-07-21

onboarding-002. Exactly ONE new table, and deliberately so: the feature spec
asks for a "demo: true metadata flag" on seeded rows, which taken literally is
a new column on eight domain tables (todos, habits, budget_categories,
budget_transactions, recipes, goals, projects, notes). A manifest recording
(household_id, entity_type, entity_id) answers the same question — "did the
seeder create this row?" — without touching any domain schema, and clearing
sample data becomes a delete driven by the manifest rather than a scan of eight
tables.

The wizard-completion flag needs no DDL at all: it lives in the existing
``users.preferences`` JSON column as ``onboarding_completed``, per member.

Plain ``create_table`` with no ALTER-shaped work, so no ``batch_alter_table``
is required and this replays identically on Postgres and SQLite. No
Postgres-only SQL, no dialect branch, and no early return for SQLite.

``entity_id`` has no foreign key on purpose — it references ten different
tables and a polymorphic FK cannot exist. ``household_id`` does cascade, so
deleting a household takes its manifest with it rather than leaving rows
pointing at entities that are already gone.
"""

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_data_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Storage-level idempotency: a second seeding pass that got past the
        # service guard still cannot record the same entity twice.
        sa.UniqueConstraint(
            "household_id", "entity_type", "entity_id", name="uq_demo_data_records_entity"
        ),
    )
    op.create_index(
        "ix_demo_data_records_household_id", "demo_data_records", ["household_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_demo_data_records_household_id", table_name="demo_data_records")
    op.drop_table("demo_data_records")
