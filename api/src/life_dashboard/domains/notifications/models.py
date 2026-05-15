import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # Fast lookups for the two most common queries:
        #   1. "fetch all unread for user X in household Y"
        #   2. "fetch recent for user X in household Y"
        Index("ix_notifications_recipient_household", "recipient_id", "household_id"),
        Index("ix_notifications_recipient_read_at", "recipient_id", "read_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)

    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    # The user who receives this notification.
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE")
    )
    # The user whose action triggered the notification (null = system-generated).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Notification type — extensible via string rather than a DB enum so new
    # types don't require migrations.
    # Current values: "todo_assigned", "event_created"
    # Planned:        "mentioned", "message_received"
    type: Mapped[str] = mapped_column(String(50))

    # Domain object that triggered the notification.
    entity_type: Mapped[str] = mapped_column(String(50))   # "todo", "calendar_event", …
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid())

    # Snapshot of the entity at notification time — avoids a join on read.
    # Shape varies by type, always includes at least {"title": str}.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Null = unread; set to timestamp when the user dismisses the notification.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
