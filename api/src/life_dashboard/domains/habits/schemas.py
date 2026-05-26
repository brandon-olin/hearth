import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from life_dashboard.core.pydantic_types import CoercedList

HabitStatus = Literal["active", "paused", "archived"]
# HabitFrequency includes "custom" for backwards compatibility with existing DB rows.
# Do NOT use it on create/update input — use HabitFrequencyInput instead.
# "custom" has no backend parser; it was removed but may exist on legacy habits.
HabitFrequency = Literal["daily", "weekly", "monthly", "custom"]
HabitFrequencyInput = Literal["daily", "weekly", "monthly"]
OccurrenceStatus = Literal["pending", "completed", "skipped"]


class HabitCreate(BaseModel):
    goal_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    frequency: HabitFrequencyInput = "daily"
    cadence: dict[str, Any] | None = None
    status: HabitStatus = "active"
    visibility: str = "personal"
    shared_with_user_ids: list[str] = []


class HabitUpdate(BaseModel):
    goal_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    frequency: HabitFrequencyInput | None = None
    cadence: dict[str, Any] | None = None
    status: HabitStatus | None = None
    visibility: str | None = None
    shared_with_user_ids: list[str] | None = None


class HabitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    goal_id: uuid.UUID | None
    name: str
    description: str | None
    frequency: str
    cadence: dict[str, Any] | None
    status: str
    visibility: str
    shared_with_user_ids: CoercedList
    created_at: datetime
    updated_at: datetime


class HabitWithStats(HabitResponse):
    """HabitResponse extended with computed stats (streak, completion rates)."""
    current_streak: int = 0
    # Completion rate as 0–100 float; None when the habit hasn't been active
    # for the full period (e.g. a new daily habit on its first week).
    completion_rate_7d: float | None = None
    completion_rate_30d: float | None = None


class HabitListResponse(BaseModel):
    items: list[HabitWithStats]
    total: int
    limit: int
    offset: int


class OccurrenceCreate(BaseModel):
    todo_id: uuid.UUID | None = None
    scheduled_date: date
    status: OccurrenceStatus = "pending"
    notes: str | None = None


class OccurrenceUpdate(BaseModel):
    todo_id: uuid.UUID | None = None
    status: OccurrenceStatus | None = None
    completed_at: datetime | None = None
    notes: str | None = None


class OccurrenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    habit_id: uuid.UUID
    todo_id: uuid.UUID | None
    scheduled_date: date
    status: str
    completed_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class OccurrenceListResponse(BaseModel):
    items: list[OccurrenceResponse]
    total: int
    limit: int
    offset: int
