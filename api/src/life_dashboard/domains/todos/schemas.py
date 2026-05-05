import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TodoStatus = Literal["pending", "in_progress", "done", "cancelled"]
TodoPriority = Literal["low", "medium", "high"]


class TodoCreate(BaseModel):
    parent_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    status: TodoStatus = "pending"
    priority: TodoPriority | None = None
    due_date: date | None = None
    recurring: dict[str, Any] | None = None


class TodoUpdate(BaseModel):
    parent_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: TodoStatus | None = None
    priority: TodoPriority | None = None
    due_date: date | None = None
    completed_at: datetime | None = None
    recurring: dict[str, Any] | None = None


class TodoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    goal_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    priority: TodoPriority | None
    due_date: date | None
    completed_at: datetime | None
    recurring: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class TodoListResponse(BaseModel):
    items: list[TodoResponse]
    total: int
    limit: int
    offset: int
