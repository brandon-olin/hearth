import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base
from life_dashboard.core.visibility import VisibilityMixin


class MealPlan(VisibilityMixin, Base):
    """One household's plan for one week.

    Household-visible by default, like recipes and grocery lists — a meal plan
    that only its author could see would be useless to the people doing the
    cooking and the shopping.
    """

    __tablename__ = "meal_plans"
    __table_args__ = (
        UniqueConstraint("household_id", "week_start", name="uq_meal_plans_household_week"),
        Index("ix_meal_plans_household_week", "household_id", "week_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL")
    )

    #: Always a Monday — normalised in the service layer, so a client may ask
    #: for any day in the week and reach the same plan.
    week_start: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entries: Mapped[list["MealPlanEntry"]] = relationship(
        "MealPlanEntry", lazy="noload", passive_deletes=True,
        order_by="MealPlanEntry.entry_date",
    )


class MealPlanEntry(Base):
    """One recipe planned into one day+slot of a plan.

    No household_id or visibility of its own — it borrows the parent plan's,
    which is why every service function loads the plan first and why semantic
    events pass the plan as ``descriptor_from``.
    """

    __tablename__ = "meal_plan_entries"
    __table_args__ = (
        CheckConstraint(
            "meal_slot IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_meal_plan_entries_slot",
        ),
        UniqueConstraint(
            "plan_id", "entry_date", "meal_slot", "recipe_id",
            name="uq_meal_plan_entries_slot_recipe",
        ),
        Index("ix_meal_plan_entries_plan_date", "plan_id", "entry_date"),
        Index("ix_meal_plan_entries_recipe", "recipe_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("meal_plans.id", ondelete="CASCADE")
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("recipes.id", ondelete="CASCADE")
    )

    entry_date: Mapped[date] = mapped_column(Date)
    meal_slot: Mapped[str] = mapped_column(String(20))
    servings: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
