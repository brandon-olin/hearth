import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class Note(Base):
    """Atomic Zettelkasten note. Each note is short-form and self-contained."""

    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(Text)
    content_md: Mapped[str | None] = mapped_column(Text)         # Raw markdown (source of truth for wikilinks)
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # BlockNote block tree (optional)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships (loaded explicitly)
    tags: Mapped[list["NoteTag"]] = relationship(
        "NoteTag", back_populates="note", lazy="noload", cascade="all, delete-orphan"
    )
    outgoing_links: Mapped[list["NoteBacklink"]] = relationship(
        "NoteBacklink", foreign_keys="NoteBacklink.source_note_id",
        back_populates="source", lazy="noload", cascade="all, delete-orphan"
    )
    incoming_links: Mapped[list["NoteBacklink"]] = relationship(
        "NoteBacklink", foreign_keys="NoteBacklink.target_note_id",
        back_populates="target", lazy="noload"
    )


class NoteTag(Base):
    """Many-to-many join between notes and the shared tags table."""

    __tablename__ = "note_tags"
    __table_args__ = (
        UniqueConstraint("note_id", "tag_id", name="note_tags_note_tag_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE")
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    note: Mapped["Note"] = relationship("Note", back_populates="tags", lazy="noload")


class NoteBacklink(Base):
    """
    A resolved [[wikilink]] from one note to another.

    Populated on save by scanning content_md for [[...]] patterns and
    resolving them against note titles in the same household. Stale links
    (where the target note no longer exists or the title changed) are deleted
    and re-resolved on each save of the source note.
    """

    __tablename__ = "note_backlinks"
    __table_args__ = (
        UniqueConstraint("source_note_id", "target_note_id", name="note_backlinks_pair_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE")
    )
    target_note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE")
    )
    # The raw text inside [[...]] as written in the source note.
    alias: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped["Note"] = relationship(
        "Note", foreign_keys=[source_note_id], back_populates="outgoing_links", lazy="noload"
    )
    target: Mapped["Note"] = relationship(
        "Note", foreign_keys=[target_note_id], back_populates="incoming_links", lazy="noload"
    )
