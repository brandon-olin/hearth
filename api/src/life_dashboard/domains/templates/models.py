import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, Text, UniqueConstraint, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class Template(Base):
    """
    A reusable content template for new collection entries.

    Templates are household-scoped by default. Setting scope="user" makes the
    template private to the creating member — other household members cannot
    see or use it.

    Templates are domain-typed ("notes" or "documents") and are only offered
    as options for collections with the matching domain.

    Content is copied into new entries at creation time. Editing a template
    does not affect previously created entries.

    Title and content fields support {{variable}} substitution resolved at
    entry-creation time using the creating user's locale settings.
    Available variables: {{date}}, {{day}}, {{day_of_week}}, {{week_number}},
    {{month}}, {{month_num}}, {{year}}, {{time}}, {{user_name}}.
    """

    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # "household" = visible to all members; "user" = private to the creator only
    scope: Mapped[str] = mapped_column(
        SaEnum("household", "user", native_enum=False),
        default="household",
        server_default="household",
    )

    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Must match the domain of any collection using this template
    domain: Mapped[str] = mapped_column(
        SaEnum("notes", "documents", native_enum=False)
    )

    # Optional: pre-fills the entry title on creation; supports {{variable}} syntax
    # e.g. "{{day_of_week}}, {{month}} {{day}}, {{year}}"
    title_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # For domain="notes" — raw markdown body; supports {{variable}} syntax
    content_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    # For domain="documents" — BlockNote block tree
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CollectionTemplate(Base):
    """
    Join table linking a Collection to its assigned Templates (many-to-many).

    Exactly one entry per collection may have is_default=True. The default
    template is used by:
      - auto-create (ensure-today), which always creates a blank or default-
        templated entry without user interaction
      - the single-template fast-path on manual entry creation (when only one
        template is assigned to the collection, skip the picker)

    When multiple templates are assigned and none is marked default, manual
    entry creation always shows the template picker.
    """

    __tablename__ = "collection_templates"
    __table_args__ = (
        UniqueConstraint(
            "collection_id", "template_id", name="collection_templates_pair_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("collections.id", ondelete="CASCADE")
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("templates.id", ondelete="CASCADE")
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
