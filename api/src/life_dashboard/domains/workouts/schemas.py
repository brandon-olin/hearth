import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ExerciseType = Literal["strength", "cardio", "hiit", "flexibility", "other"]


# ── Exercise entry ─────────────────────────────────────────────────────────────

class ExerciseEntryCreate(BaseModel):
    name: str
    type: ExerciseType
    sort_order: int = 0
    metrics: dict[str, Any] | None = None
    notes: str | None = None


class ExerciseEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    type: ExerciseType | None = None
    sort_order: int | None = None
    metrics: dict[str, Any] | None = None
    notes: str | None = None


class ExerciseEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workout_id: uuid.UUID
    name: str
    type: str
    sort_order: int
    metrics: dict[str, Any] | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ── Workout ────────────────────────────────────────────────────────────────────

class WorkoutCreate(BaseModel):
    workout_date: date
    name: str | None = None
    notes: str | None = None
    # Optionally inline entries on creation — saves a round-trip for the common
    # case of logging a workout with exercises in one shot.
    entries: list[ExerciseEntryCreate] = []


class WorkoutUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    workout_date: date | None = None
    notes: str | None = None


class WorkoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    name: str | None
    workout_date: date
    notes: str | None
    created_at: datetime
    updated_at: datetime
    # Populated by list_workouts for the card summary; empty on single-fetch responses.
    exercise_names: list[str] = []


class WorkoutWithEntriesResponse(WorkoutResponse):
    """Single-workout detail view — includes the ordered exercise list."""
    entries: list[ExerciseEntryResponse] = []


class WorkoutListResponse(BaseModel):
    items: list[WorkoutResponse]
    total: int
    limit: int
    offset: int
