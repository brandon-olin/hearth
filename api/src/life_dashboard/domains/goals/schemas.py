import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GoalStatus = Literal["active", "completed", "paused", "archived"]
GoalPriority = Literal["low", "medium", "high"]


class GoalCreate(BaseModel):
    parent_id: uuid.UUID | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    status: GoalStatus = "active"
    priority: GoalPriority | None = None
    target_value: Decimal | None = None
    current_value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=100)
    due_date: date | None = None


class GoalUpdate(BaseModel):
    parent_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: GoalStatus | None = None
    priority: GoalPriority | None = None
    target_value: Decimal | None = None
    current_value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=100)
    due_date: date | None = None
    completed_at: datetime | None = None


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    priority: GoalPriority | None
    target_value: Decimal | None
    current_value: Decimal | None
    unit: str | None
    due_date: date | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GoalListResponse(BaseModel):
    items: list[GoalResponse]
    total: int
    limit: int
    offset: int
