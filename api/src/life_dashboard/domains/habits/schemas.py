import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HabitStatus = Literal["active", "paused", "archived"]
HabitFrequency = Literal["daily", "weekly", "monthly", "custom"]
OccurrenceStatus = Literal["pending", "completed", "skipped"]


class HabitCreate(BaseModel):
    goal_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    frequency: HabitFrequency = "daily"
    cadence: dict[str, Any] | None = None
    status: HabitStatus = "active"


class HabitUpdate(BaseModel):
    goal_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    frequency: HabitFrequency | None = None
    cadence: dict[str, Any] | None = None
    status: HabitStatus | None = None


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
    created_at: datetime
    updated_at: datetime


class HabitListResponse(BaseModel):
    items: list[HabitResponse]
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
