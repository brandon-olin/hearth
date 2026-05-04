import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("household_id", "name", name="tags_household_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Tagging(Base):
    __tablename__ = "taggings"
    __table_args__ = (
        UniqueConstraint("tag_id", "entity_type", "entity_id", name="taggings_tag_entity_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE")
    )
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
