import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy import Enum as SaEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class Collection(Base):
    """
    A user-defined named view over a domain (notes or documents).

    Collections provide:
    - A custom name and icon shown in the sidebar
    - Default tags auto-applied to new items created inside the collection
    - An optional document template pre-populated on item creation
    - An optional auto_create_rule for scheduled entry generation
      (e.g. {"frequency": "daily", "title_template": "%B %d, %Y"})
    """

    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "notes" or "documents"
    domain: Mapped[str] = mapped_column(
        SaEnum("notes", "documents", name="collection_domain", create_type=False)
    )

    # JSONB array of tag UUID strings — avoids a join table for short lists
    default_tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Optional template document to pre-populate new items
    default_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    # e.g. {"frequency": "daily", "title_template": "%B %d, %Y"}
    auto_create_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
