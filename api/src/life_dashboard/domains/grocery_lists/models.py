import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base
from life_dashboard.core.visibility import VisibilityMixin


class GroceryList(VisibilityMixin, Base):
    __tablename__ = "grocery_lists"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL")
    )
    todo_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("todos.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(500))
    store: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(50), default="active")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["GroceryItem"]] = relationship(
        "GroceryItem", lazy="noload", passive_deletes=True
    )


class GroceryItem(Base):
    __tablename__ = "grocery_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("grocery_lists.id", ondelete="CASCADE")
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("recipes.id", ondelete="SET NULL")
    )
    recipe_ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("recipe_ingredients.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(200))
    is_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
