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


async def _sync_financial_link(
    db: AsyncSession,
    financial_link: dict | None,
) -> None:
    """
    If a spending_cap link is set, keep BudgetCategory.default_monthly_amount
    in sync with the goal's monthly_limit.
    """
    if not financial_link or financial_link.get("type") != "spending_cap":
        return
    category_id_str = financial_link.get("category_id")
    monthly_limit = financial_link.get("monthly_limit")
    if not category_id_str or monthly_limit is None:
        return

    try:
        category_id = uuid.UUID(category_id_str)
    except (ValueError, AttributeError):
        return

    from life_dashboard.domains.budget.models import BudgetCategory
    result = await db.execute(select(BudgetCategory).where(BudgetCategory.id == category_id))
    category = result.scalar_one_or_none()
    if category is not None:
        category.default_monthly_amount = float(monthly_limit)


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
        financial_link=data.financial_link,
    )
    db.add(goal)
    await _sync_financial_link(db, data.financial_link)
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
    result = await db.execute(query)
    goal = result.scalar_one_or_none()
    if goal is None:
        return None

    for field in data.model_fields_set:
        setattr(goal, field, getattr(data, field))

    # Sync spending_cap to budget category if financial_link was updated
    if "financial_link" in data.model_fields_set:
        await _sync_financial_link(db, data.financial_link)

    await db.commit()
    await db.refresh(goal)
    return _to_response(goal)


async def delete_goal(
    db: AsyncSession,
    goal_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    query = select(Goal).where(Goal.id == goal_id, Goal.household_id == household_id)
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
