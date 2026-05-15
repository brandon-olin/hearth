from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel
from life_dashboard.core.pydantic_types import CoercedList

ProjectStatus = Literal["backlog", "active", "on_deck", "in_progress", "complete", "archived"]


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    status: ProjectStatus = "active"
    due_date: date | None = None
    parent_id: uuid.UUID | None = None
    show_in_nav: bool = False
    sort_order: int = 0
    visibility: str = "household"
    shared_with_user_ids: list[str] = []


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    due_date: date | None = None
    parent_id: uuid.UUID | None = None
    show_in_nav: bool | None = None
    sort_order: int | None = None
    visibility: str | None = None
    shared_with_user_ids: list[str] | None = None


class ProjectResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    name: str
    description: str | None
    status: ProjectStatus
    due_date: date | None
    is_system: bool
    show_in_nav: bool
    sort_order: int
    archived_at: datetime | None
    visibility: str
    shared_with_user_ids: CoercedList
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int


# ── Goal-relationship schemas ─────────────────────────────────────────────────

class ProjectGoalLink(BaseModel):
    """Returned when a goal is linked/unlinked from a project."""
    project_id: uuid.UUID
    goal_id: uuid.UUID


class ProjectGoalListResponse(BaseModel):
    items: list[uuid.UUID]  # list of goal IDs linked to the project
    total: int
