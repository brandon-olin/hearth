import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.notifications.models import Notification
from life_dashboard.domains.notifications.schemas import (
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)


# ── dispatch helpers (called by other domain services) ───────────────────────

async def dispatch(
    db: AsyncSession,
    *,
    household_id: uuid.UUID,
    recipient_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
) -> Notification:
    """Create a single notification row. Does NOT commit — callers own the transaction."""
    # Never notify a user about their own action.
    if actor_id is not None and recipient_id == actor_id:
        return None  # type: ignore[return-value]

    n = Notification(
        household_id=household_id,
        recipient_id=recipient_id,
        actor_id=actor_id,
        type=type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    db.add(n)
    return n


async def dispatch_to_household(
    db: AsyncSession,
    *,
    household_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    exclude_user_ids: list[uuid.UUID] | None = None,
    type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict[str, Any] | None = None,
) -> None:
    """Dispatch a notification to every member of the household except the actor
    and any explicitly excluded user IDs. Does NOT commit."""
    from life_dashboard.auth.models import HouseholdMembership

    result = await db.execute(
        select(HouseholdMembership.user_id).where(
            HouseholdMembership.household_id == household_id
        )
    )
    member_ids: list[uuid.UUID] = list(result.scalars().all())
    excluded = set(exclude_user_ids or [])
    if actor_id is not None:
        excluded.add(actor_id)

    for member_id in member_ids:
        if member_id in excluded:
            continue
        n = Notification(
            household_id=household_id,
            recipient_id=member_id,
            actor_id=actor_id,
            type=type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        db.add(n)


# ── read endpoints ────────────────────────────────────────────────────────────

async def list_notifications(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    limit: int = 30,
    offset: int = 0,
    unread_only: bool = False,
) -> NotificationListResponse:
    base_q = select(Notification).where(
        Notification.household_id == household_id,
        Notification.recipient_id == user_id,
    )
    if unread_only:
        base_q = base_q.where(Notification.read_at.is_(None))

    total = (
        await db.execute(select(func.count()).select_from(base_q.subquery()))
    ).scalar_one()

    unread_count = (
        await db.execute(
            select(func.count()).select_from(
                select(Notification)
                .where(
                    Notification.household_id == household_id,
                    Notification.recipient_id == user_id,
                    Notification.read_at.is_(None),
                )
                .subquery()
            )
        )
    ).scalar_one()

    items = list(
        (
            await db.execute(
                base_q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
        unread_count=unread_count,
    )


async def get_unread_count(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> UnreadCountResponse:
    count = (
        await db.execute(
            select(func.count()).select_from(
                select(Notification)
                .where(
                    Notification.household_id == household_id,
                    Notification.recipient_id == user_id,
                    Notification.read_at.is_(None),
                )
                .subquery()
            )
        )
    ).scalar_one()
    return UnreadCountResponse(unread_count=count)


async def mark_read(
    db: AsyncSession,
    notification_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.household_id == household_id,
            Notification.recipient_id == user_id,
        )
    )
    n = result.scalar_one_or_none()
    if n is None:
        return False
    if n.read_at is None:
        n.read_at = datetime.now(tz=timezone.utc)
        await db.commit()
    return True


async def mark_all_read(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    """Mark all unread notifications for a user as read. Returns the count updated."""
    now = datetime.now(tz=timezone.utc)
    result = await db.execute(
        update(Notification)
        .where(
            Notification.household_id == household_id,
            Notification.recipient_id == user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    await db.commit()
    return result.rowcount
