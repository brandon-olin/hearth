import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.visibility import apply_visibility_filter
from life_dashboard.domains.goals.models import Goal
from life_dashboard.domains.goals.schemas import (
    GoalCreate,
    GoalListResponse,
    GoalProjectListResponse,
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
        visibility=data.visibility,
        shared_with_user_ids=data.shared_with_user_ids or [],
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return _to_response(goal)


async def get_goal(
    db: AsyncSession,
    goal_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> GoalResponse | None:
    query = select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Goal, user_id)
    result = await db.execute(query)
    goal = result.scalar_one_or_none()
    return _to_response(goal) if goal else None


async def list_goals(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    *,
    status: str | None = None,
    parent_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> GoalListResponse:
    query = select(Goal).where(Goal.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Goal, user_id)
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
    query = select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Goal, user_id)
    result = await db.execute(query)
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
    query = select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id)
    if user_id is not None:
        query = apply_visibility_filter(query, Goal, user_id)
    result = await db.execute(query)
    goal = result.scalar_one_or_none()
    if goal is None:
        return False
    await db.delete(goal)
    await db.commit()
    return True


# ── Project relationships ─────────────────────────────────────────────────────

async def list_goal_projects(
    db: AsyncSession,
    goal_id: uuid.UUID,
    household_id: uuid.UUID,
) -> GoalProjectListResponse | None:
    """Return the project IDs linked to a goal. Returns None if goal not found."""
    from life_dashboard.domains.projects.models import ProjectGoal

    # Verify the goal belongs to this household
    exists = (await db.execute(
        select(Goal.id).where(Goal.id == goal_id, Goal.household_id == household_id)
    )).scalar_one_or_none()
    if not exists:
        return None

    rows = (await db.execute(
        select(ProjectGoal.project_id).where(ProjectGoal.goal_id == goal_id)
    )).scalars().all()
    return GoalProjectListResponse(items=list(rows), total=len(rows))
