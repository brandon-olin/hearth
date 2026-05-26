import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class Collection(Base):
    """
    A user-defined named view over a domain (notes or documents).

    Collections provide:
    - A custom name and icon shown in the sidebar
    - Default tags auto-applied to new items created inside the collection
    - One or more Templates (via CollectionTemplate join) for pre-populating
      new entries; one may be marked is_default for auto-create
    - An optional auto_create_rule for scheduled entry generation
      (e.g. {"frequency": "daily", "title_template": "{{day_of_week}}, {{month}} {{day}}, {{year}}"})
    - show_in_nav controls whether this collection appears in the sidebar;
      defaults to False (explicit opt-in via Navigation settings)
    """

    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "notes" or "documents"
    domain: Mapped[str] = mapped_column(
        SaEnum("notes", "documents", native_enum=False)
    )

    # Optional semantic flag identifying this collection's role to other
    # subsystems. NULL = a generic user-named collection. Recognized values
    # today: "journal" (notes in this collection are fed to the journal
    # signal extractor and read by the CBT-aware coach). Reserved for future:
    # "recipes", "routines". Stored as a free String (no native enum) so new
    # kinds can be added without a DB migration. See migration 0032.
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # JSON array of tag UUID strings — avoids a join table for short lists
    default_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # {"frequency": "daily", "title_template": "{{variable}} ..."} — uses
    # {{variable}} syntax (not strftime); resolved with creating user's locale.
    auto_create_rule: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Whether this collection appears in the sidebar. Defaults False — the user
    # must explicitly add it via Navigation settings after creation.
    show_in_nav: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
