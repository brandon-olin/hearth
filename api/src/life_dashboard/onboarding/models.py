import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base

#: Entity kinds the seeder can create, in the order they must be *deleted* —
#: children before the parents they hang off, so a cascade never runs ahead of
#: the manifest and takes a row the user created with it.
DEMO_ENTITY_TYPES: tuple[str, ...] = (
    "budget_transaction",
    "todo",
    "habit",
    "recipe",
    "note",
    "goal",
    "project",
    "budget_category",
    "budget_category_group",
    "budget_account",
)


class DemoDataRecord(Base):
    """One row of sample data the first-run seeder created (onboarding-002).

    The alternative — a ``demo BOOLEAN`` column on todos, habits, recipes,
    goals, projects, notes, budget_categories and budget_transactions — spends
    eight schema changes to answer one question that is asked twice in the
    product's life: "did we make this row, and may we delete it?" A manifest
    answers it with one table and no reach into the domains.

    The unique constraint is what makes seeding idempotent at the storage layer:
    a second seeding pass that somehow got past the service-level guard still
    cannot double-record an entity.

    ``entity_id`` carries no foreign key. It points at ten different tables, and
    a polymorphic FK cannot exist; the clear path therefore always deletes the
    real row and its manifest entry in the same transaction, and tolerates a
    missing row (already gone) rather than assuming referential integrity it
    does not have.
    """

    __tablename__ = "demo_data_records"
    __table_args__ = (
        UniqueConstraint(
            "household_id", "entity_type", "entity_id", name="uq_demo_data_records_entity"
        ),
        Index("ix_demo_data_records_household_id", "household_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    #: One of DEMO_ENTITY_TYPES. Not a CHECK constraint — the vocabulary grows
    #: whenever the seeder learns a new domain, and a stale value here is inert
    #: (the clear path skips entity types it doesn't recognise) rather than a
    #: write failure.
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
