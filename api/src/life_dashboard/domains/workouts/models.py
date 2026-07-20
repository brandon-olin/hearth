import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Uuid,
)
from sqlalchemy import Enum as SaEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base
from life_dashboard.core.visibility import VisibilityMixin

# ── Constrained string types (VARCHAR + CHECK on both engines, ADR-015) ─────────
# native_enum=False keeps these portable: Postgres and SQLite both get a VARCHAR
# column plus a CHECK constraint, never a native pg enum type (which would drift
# between the create_all() and Alembic-replay schemas).

#: How an exercise's sets are measured. Drives which set fields the UI collects.
_tracking_type = SaEnum(
    "reps", "duration", "distance",
    native_enum=False, name="exercise_tracking_type", create_constraint=True,
)
_weight_unit = SaEnum(
    "lbs", "kg",
    native_enum=False, name="workout_weight_unit", create_constraint=True,
)
_distance_unit = SaEnum(
    "km", "mi",
    native_enum=False, name="workout_distance_unit", create_constraint=True,
)


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
    # Stored as VARCHAR + CHECK on both engines. Migration 0047 converted the
    # native `exercise_type` enum away and dropped the type (ADR-015).
    type: Mapped[str] = mapped_column(
        SaEnum(
            "strength", "cardio", "hiit", "flexibility", "other",
            native_enum=False,
            name="exercise_type",
            create_constraint=True,
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


# ── workouts-001: first-class sets, exercise library, superset groups ───────────
#
# These six tables SUPERSEDE the legacy Workout/ExerciseEntry pair above, which is
# left in place so the existing /workouts endpoints and their frontend keep
# working during the workouts-002..005 UI migration. Migration 0048 backfills the
# legacy rows forward into workout_sessions/session_exercises/workout_sets.
#
# Scoping (feature UPDATE 2026-07-20): workouts are PERSONAL, templates and
# exercises are SHARED — but "personal" is a read-time filter on
# created_by_user_id, never an omitted column. Every table keeps household_id so
# household deletion cascades cleanly and exports stay household-shaped. These
# tables deliberately do NOT use VisibilityMixin: there is no per-workout
# visibility control.


class Exercise(Base):
    """A movement in the exercise catalog.

    ``household_id IS NULL`` marks an app-wide seeded library entry
    (``is_global=True``, the ~60 rows migration 0048 seeds). A non-NULL
    household_id is a custom exercise created within that household and visible
    only to its members.
    """
    __tablename__ = "exercises"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    # NULL = global library entry (shared app-wide). Non-NULL = household-custom.
    household_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    # List of muscle-group slugs, e.g. ["chest", "triceps"]. Read defensively.
    muscle_groups: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    equipment_type: Mapped[str | None] = mapped_column(Text)
    tracking_type: Mapped[str] = mapped_column(_tracking_type, nullable=False)
    is_global: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Soft delete for custom exercises; global rows are never archived.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkoutTemplate(Base):
    """A reusable workout plan, SHARED across the whole household.

    No ``last_used_at`` column: with shared templates it is ambiguous (used by
    whom?) and would go stale. Recency is derived per-user at query time —
    MAX(workout_sessions.started_at) WHERE template_id = :t AND
    created_by_user_id = :me.
    """
    __tablename__ = "workout_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The member who built it. Nullable + SET NULL so deleting a user never
    # destroys a household-shared template.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateExercise(Base):
    """One exercise slot within a template, with default set targets.

    ``superset_group_id`` groups 2–5 slots into a superset (enforced at the
    service layer). A heavy-bench slot and a back-off-bench slot are distinct
    rows even for the same exercise, so their history tracks independently.
    """
    __tablename__ = "template_exercises"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("workout_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # CASCADE: a template slot is meaningless without its exercise. History
    # (session_exercises) uses a softer rule — see SessionExercise.
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    superset_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)

    default_sets: Mapped[int | None] = mapped_column(Integer)
    default_reps: Mapped[int | None] = mapped_column(Integer)
    default_weight: Mapped[float | None] = mapped_column(Numeric(7, 2))
    default_rest_seconds: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkoutSession(Base):
    """A logged (or in-progress) workout. PERSONAL: every read filters
    ``created_by_user_id = current user``.

    ``template_id`` is a nullable FK with ON DELETE SET NULL — deleting a
    template must not destroy anyone's logs. Sessions materialize their own
    session_exercises and workout_sets at start, so past history survives a
    template deletion intact; only future prefill is affected.
    """
    __tablename__ = "workout_sessions"
    __table_args__ = (
        # Personal list (household + owner, newest first) and calendar reads.
        Index(
            "ix_workout_sessions_hh_user_started",
            "household_id", "created_by_user_id", "started_at",
        ),
        # Per-user template recency (last_used_at derivation).
        Index(
            "ix_workout_sessions_template_user",
            "template_id", "created_by_user_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("workout_templates.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionExercise(Base):
    """One exercise as it appears in a logged session.

    ``template_exercise_id`` is a nullable FK (ON DELETE SET NULL) linking back
    to the template slot this was seeded from — ghost-value prefill keys on it so
    protocol variants stay independent. History is preserved when a template
    (and its slots) is deleted: the link nulls, the rows remain.
    """
    __tablename__ = "session_exercises"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("workout_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # No ondelete cascade from exercises: a session is a historical record and
    # must outlive catalog edits. Exercises are soft-deleted (archived_at), so a
    # referenced exercise is not hard-deleted in normal operation.
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("exercises.id"), nullable=False, index=True
    )
    template_exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("template_exercises.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    superset_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkoutSet(Base):
    """A single set within a session exercise — the first-class unit this
    refactor introduces (the legacy model stored an aggregate on the entry row).
    """
    __tablename__ = "workout_sets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    session_exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("session_exercises.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    set_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    reps: Mapped[int | None] = mapped_column(Integer)
    # Planned reps — logged reps < target_reps flags a failed set (workouts-004).
    target_reps: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[float | None] = mapped_column(Numeric(7, 2))
    weight_unit: Mapped[str | None] = mapped_column(_weight_unit)
    distance_meters: Mapped[float | None] = mapped_column(Numeric(10, 2))
    distance_unit: Mapped[str | None] = mapped_column(_distance_unit)
    rest_seconds: Mapped[int | None] = mapped_column(Integer)
    is_warmup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Rate of perceived exertion, 1–10 (validated in schemas).
    rpe: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
