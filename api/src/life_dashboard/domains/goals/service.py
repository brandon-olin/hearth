import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.goals.models import Goal
from life_dashboard.domains.goals.schemas import (
    GoalCreate,
    GoalListResponse,
    GoalResponse,
    GoalUpdate,
)


def _to_response(goal: Goal) -> GoalResponse:
    return GoalResponse.model_validate(goal)


async def create_goal(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: GoalCreate,
) -> GoalResponse:
    goal = Goal(
        household_id=household_id,
        created_by_user_id=user_id,
        parent_id=data.parent_id,
        title=data.title,
        description=data.description,
        status=data.status,
        priority=data.priority,
        target_value=data.target_value,
        current_value=data.current_value,
        unit=data.unit,
        due_date=data.due_date,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return _to_response(goal)


async def get_goal(
    db: AsyncSession,
    goal_id: uuid.UUID,
    household_id: uuid.UUID,
) -> GoalResponse | None:
    result = await db.execute(
        select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id)
    )
    goal = result.scalar_one_or_none()
    return _to_response(goal) if goal else None


async def list_goals(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    status: str | None = None,
    parent_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> GoalListResponse:
    query = select(Goal).where(Goal.household_id == household_id)
    if status is not None:
        query = query.where(Goal.status == status)
    if parent_id is not None:
        query = query.where(Goal.parent_id == parent_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    goals = list(
        (await db.execute(
            query.order_by(Goal.created_at.desc()).limit(limit).offset(offset)
        )).scalars().all()
    )
    return GoalListResponse(
        items=[_to_response(g) for g in goals],
        total=total, limit=limit, offset=offset,
    )


async def update_goal(
    db: AsyncSession,
    goal_id: uuid.UUID,
    household_id: uuid.UUID,
    data: GoalUpdate,
) -> GoalResponse | None:
    result = await db.execute(
        select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id)
    )
    goal = result.scalar_one_or_none()
    if goal is None:
        return None

    for field in data.model_fields_set:
        setattr(goal, field, getattr(data, field))

    await db.commit()
    await db.refresh(goal)
    return _to_response(goal)


async def delete_goal(
    db: AsyncSession,
    goal_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id)
    )
    goal = result.scalar_one_or_none()
    if goal is None:
        return False
    await db.delete(goal)
    await db.commit()
    return True
