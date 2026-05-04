import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CalendarEventStatus = Literal["tentative", "confirmed", "cancelled"]
CalendarEventTransparency = Literal["opaque", "transparent"]


class CalendarEventCreate(BaseModel):
    ical_uid: str | None = None
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    location: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    rrule: str | None = None
    exrule: str | None = None
    rdate: str | None = None
    exdate: str | None = None
    status: CalendarEventStatus = "confirmed"
    transparency: CalendarEventTransparency = "opaque"
    todo_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    source: str | None = None
    external_id: str | None = None
    calendar_name: str | None = None


class CalendarEventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    location: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool | None = None
    rrule: str | None = None
    exrule: str | None = None
    rdate: str | None = None
    exdate: str | None = None
    status: CalendarEventStatus | None = None
    transparency: CalendarEventTransparency | None = None
    todo_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    calendar_name: str | None = None


class CalendarEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    todo_id: uuid.UUID | None
    goal_id: uuid.UUID | None
    ical_uid: str
    title: str
    description: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool
    rrule: str | None
    exrule: str | None
    rdate: str | None
    exdate: str | None
    status: str
    transparency: str
    source: str | None
    external_id: str | None
    calendar_name: str | None
    created_at: datetime
    updated_at: datetime


class CalendarEventListResponse(BaseModel):
    items: list[CalendarEventResponse]
    total: int
    limit: int
    offset: int
