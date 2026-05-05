import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy import Enum as SaEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("household_id", "slug", name="documents_household_slug_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(
        SaEnum("page", "template", name="document_kind", create_type=False),
        default="page",
    )
    source_markdown: Mapped[str | None] = mapped_column(Text)
    editor_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Children loaded explicitly via bulk query — never via this relationship.
    children: Mapped[list["Document"]] = relationship("Document", lazy="noload", passive_deletes=True)
