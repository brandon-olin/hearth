import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    todo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("todos.id", ondelete="SET NULL")
    )
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="SET NULL")
    )

    ical_uid: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(500))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    rrule: Mapped[str | None] = mapped_column(Text)
    exrule: Mapped[str | None] = mapped_column(Text)
    rdate: Mapped[str | None] = mapped_column(Text)
    exdate: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    transparency: Mapped[str] = mapped_column(String(20), default="opaque")
    source: Mapped[str | None] = mapped_column(String(100))
    external_id: Mapped[str | None] = mapped_column(Text)
    calendar_name: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
