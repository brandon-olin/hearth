import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.calendar_events.models import CalendarEvent
from life_dashboard.domains.calendar_events.schemas import (
    CalendarEventCreate,
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventUpdate,
)
from life_dashboard.domains.notifications import service as notifications


async def create_event(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CalendarEventCreate,
) -> CalendarEventResponse:
    ical_uid = data.ical_uid or f"ld-{uuid.uuid4()}@life-dashboard.local"
    event = CalendarEvent(
        household_id=household_id,
        created_by_user_id=user_id,
        ical_uid=ical_uid,
        title=data.title,
        description=data.description,
        location=data.location,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        all_day=data.all_day,
        rrule=data.rrule,
        exrule=data.exrule,
        rdate=data.rdate,
        exdate=data.exdate,
        status=data.status,
        transparency=data.transparency,
        todo_id=data.todo_id,
        goal_id=data.goal_id,
        source=data.source,
        external_id=data.external_id,
        calendar_name=data.calendar_name,
    )
    db.add(event)
    await db.flush()  # get event.id before committing

    # Notify all other household members that a new event was added.
    # Skip external-sync events (source is set) to avoid flooding the feed
    # during a bulk calendar import.
    if not data.source:
        await notifications.dispatch_to_household(
            db,
            household_id=household_id,
            actor_id=user_id,
            type="event_created",
            entity_type="calendar_event",
            entity_id=event.id,
            payload={
                "title": event.title,
                "starts_at": event.starts_at.isoformat(),
            },
        )

    await db.commit()
    await db.refresh(event)
    return CalendarEventResponse.model_validate(event)


async def get_event(
    db: AsyncSession,
    event_id: uuid.UUID,
    household_id: uuid.UUID,
) -> CalendarEventResponse | None:
    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.household_id == household_id,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        return None
    return CalendarEventResponse.model_validate(event)


async def list_events(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> CalendarEventListResponse:
    query = select(CalendarEvent).where(CalendarEvent.household_id == household_id)
    if starts_after is not None:
        query = query.where(CalendarEvent.starts_at >= starts_after)
    if starts_before is not None:
        query = query.where(CalendarEvent.starts_at <= starts_before)
    if status is not None:
        query = query.where(CalendarEvent.status == status)
    if search:
        query = query.where(CalendarEvent.title.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    events = list(
        (await db.execute(
            query.order_by(CalendarEvent.starts_at.asc()).limit(limit).offset(offset)
        )).scalars().all()
    )
    return CalendarEventListResponse(
        items=[CalendarEventResponse.model_validate(e) for e in events],
        total=total, limit=limit, offset=offset,
    )


async def update_event(
    db: AsyncSession,
    event_id: uuid.UUID,
    household_id: uuid.UUID,
    data: CalendarEventUpdate,
) -> CalendarEventResponse | None:
    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.household_id == household_id,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        return None

    sent = data.model_fields_set
    for field in ("title", "description", "location", "starts_at", "ends_at", "all_day",
                  "rrule", "exrule", "rdate", "exdate", "status", "transparency",
                  "todo_id", "goal_id", "calendar_name"):
        if field in sent:
            setattr(event, field, getattr(data, field))

    await db.commit()
    await db.refresh(event)
    return CalendarEventResponse.model_validate(event)


async def delete_event(
    db: AsyncSession,
    event_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.household_id == household_id,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        return False
    await db.delete(event)
    await db.commit()
    return True
