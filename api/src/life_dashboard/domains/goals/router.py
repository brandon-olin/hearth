import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.core.permissions import (
    check_permission,
    get_item_creator,
    load_household_permissions,
)
from life_dashboard.domains.goals.models import Goal
from life_dashboard.domains.goals.schemas import (
    GoalCreate,
    GoalListResponse,
    GoalProjectListResponse,
    GoalResponse,
    GoalUpdate,
)
from life_dashboard.domains.goals import service

router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("", response_model=GoalListResponse)
async def list_goals(
    status: str | None = Query(default=None),
    parent_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalListResponse:
    return await service.list_goals(
        db, current_user.household_id, current_user.id,
        status=status, parent_id=parent_id, limit=limit, offset=offset,
    )


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalResponse:
    goal = await service.get_goal(db, goal_id, current_user.household_id, user_id=current_user.id)
    if goal is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return goal


@router.post("", response_model=GoalResponse, status_code=http_status.HTTP_201_CREATED)
async def create_goal(
    data: GoalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalResponse:
    perms = await load_household_permissions(db, current_user.household_id)
    if not check_permission(perms, "goals", "create", current_user.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to create goals.",
        )
    return await service.create_goal(db, current_user.household_id, current_user.id, data)


@router.patch("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: uuid.UUID,
    data: GoalUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalResponse:
    creator_id = await get_item_creator(db, Goal, goal_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Goal not found")
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "goals", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit others' goals.",
            )
    goal = await service.update_goal(db, goal_id, current_user.household_id, data)
    if goal is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return goal


@router.delete("/{goal_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    creator_id = await get_item_creator(db, Goal, goal_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Goal not found")
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "goals", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete others' goals.",
            )
    deleted = await service.delete_goal(db, goal_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Goal not found")


# ── Project relationships ─────────────────────────────────────────────────────

@router.get("/{goal_id}/projects", response_model=GoalProjectListResponse)
async def list_goal_projects(
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalProjectListResponse:
    """Return the project IDs linked to a goal."""
    result = await service.list_goal_projects(db, goal_id, current_user.household_id)
    if result is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return result
