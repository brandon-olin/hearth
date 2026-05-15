import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from life_dashboard.core.pydantic_types import CoercedList

TodoStatus = Literal["pending", "in_progress", "done", "cancelled"]
TodoPriority = Literal["low", "medium", "high"]
RecurrenceFrequency = Literal[
    "daily",            # every N days
    "weekdays",         # every weekday (Mon–Fri), interval ignored
    "weekly",           # every N weeks on days_of_week
    "monthly_date",     # every N months on the same numeric date
    "monthly_weekday",  # every N months on the same Nth weekday (e.g. 2nd Tuesday)
    "yearly",           # every N years on the same month/day
]


class RecurrenceRule(BaseModel):
    """Structured recurrence rule stored as JSONB on the Todo model."""

    frequency: RecurrenceFrequency
    interval: int = Field(default=1, ge=1, le=365)
    # For weekly: list of Python weekdays (0=Mon … 6=Sun) to recur on.
    days_of_week: list[int] | None = None
    # Optional end date; no new instances spawned after this date.
    end_date: date | None = None


class TodoCreate(BaseModel):
    project_id: uuid.UUID | None = None
    assigned_to_user_id: uuid.UUID | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    status: TodoStatus = "pending"
    priority: TodoPriority | None = None
    due_date: date | None = None
    recurring: dict[str, Any] | None = None
    link_url: str | None = None
    visibility: str = "household"
    shared_with_user_ids: list[str] = Field(default_factory=list)


class TodoUpdate(BaseModel):
    project_id: uuid.UUID | None = None
    assigned_to_user_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: TodoStatus | None = None
    priority: TodoPriority | None = None
    due_date: date | None = None
    completed_at: datetime | None = None
    recurring: dict[str, Any] | None = None
    link_url: str | None = None
    visibility: str | None = None
    shared_with_user_ids: list[str] | None = None


class TodoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    assigned_to_user_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    priority: TodoPriority | None
    due_date: date | None
    completed_at: datetime | None
    recurring: dict[str, Any] | None
    link_url: str | None
    visibility: str
    shared_with_user_ids: CoercedList
    created_at: datetime
    updated_at: datetime


class TodoListResponse(BaseModel):
    items: list[TodoResponse]
    total: int
    limit: int
    offset: int
