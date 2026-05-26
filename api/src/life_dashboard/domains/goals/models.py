import uuid
from datetime import date, datetime
from decimal import Decimal

from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, JSON, Numeric, String, Text, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base
from life_dashboard.core.visibility import VisibilityMixin


class Goal(VisibilityMixin, Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("goals.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="active")
    priority: Mapped[str | None] = mapped_column(
        SaEnum("low", "medium", "high", native_enum=False)
    )
    target_value: Mapped[Decimal | None] = mapped_column(Numeric)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric, default=0)
    unit: Mapped[str | None] = mapped_column(String(100))
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Optional link to a budget entity for live progress tracking.
    # Shape: { "type": "spending_cap"|"savings_target"|"debt_payoff",
    #          "category_id"/"account_id": "<uuid>",
    #          "monthly_limit"/"target_amount"/"target_balance": <float> }
    # When type="spending_cap", monthly_limit is kept in sync with
    # BudgetCategory.default_monthly_amount automatically.
    financial_link: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    children: Mapped[list["Goal"]] = relationship("Goal", lazy="noload", passive_deletes=True)
