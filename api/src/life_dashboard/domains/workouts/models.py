import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, Text, Uuid
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base
from life_dashboard.core.visibility import VisibilityMixin


class Workout(VisibilityMixin, Base):
    __tablename__ = "workouts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL")
    )

    name: Mapped[str | None] = mapped_column(Text)
    workout_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # lazy="noload" — no implicit SELECT; entries are loaded explicitly in service.py
    entries: Mapped[list["ExerciseEntry"]] = relationship(
        "ExerciseEntry", lazy="noload", passive_deletes=True
    )


class ExerciseEntry(Base):
    __tablename__ = "exercise_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    workout_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("workouts.id", ondelete="CASCADE")
    )

    name: Mapped[str] = mapped_column(Text)
    # exercise_type enum is created by migration 0007; create_type=False prevents
    # SQLAlchemy from trying to CREATE TYPE at schema-sync time.
    type: Mapped[str] = mapped_column(
        SaEnum(
            "strength", "cardio", "hiit", "flexibility", "other",
            native_enum=False,
        )
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Shape varies by type:
    #   strength   → {sets, reps, weight_kg}
    #   cardio     → {duration_seconds, distance_meters, avg_heart_rate}
    #   hiit       → {rounds, work_seconds, rest_seconds}
    #   flexibility / other → freeform keys
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
