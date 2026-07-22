import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.core.permissions import check_permission, load_household_permissions
from life_dashboard.domains.meal_plans import service
from life_dashboard.domains.meal_plans.schemas import (
    GenerateGroceryListRequest,
    GenerateGroceryListResponse,
    MealPlanCreate,
    MealPlanEntryCreate,
    MealPlanEntryResponse,
    MealPlanEntryUpdate,
    MealPlanListResponse,
    MealPlanResponse,
    MealPlanUpdate,
)

router = APIRouter(prefix="/meal-plans", tags=["meal_plans"])


async def _require(
    db: AsyncSession, user: User, domain: str, action: str, message: str
) -> None:
    """Gate a write on the household's configured permissions.

    Planning meals is governed by the **recipes** permission — it is recipe-
    library activity, and a household that lets a member add recipes has
    already decided they may plan dinner. Generating a shopping list
    additionally needs **grocery** create, because that is what it writes.
    Reusing the two existing domains keeps one settings screen honest rather
    than adding a third knob that means the same thing.
    """
    perms = await load_household_permissions(db, user.household_id)
    if not check_permission(perms, domain, action, user.role):
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=message)


@router.get("", response_model=MealPlanListResponse)
async def list_meal_plans(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealPlanListResponse:
    return await service.list_plans(
        db, current_user.household_id, current_user.id, limit=limit, offset=offset
    )


@router.get("/week", response_model=MealPlanResponse | None)
async def get_week(
    day: date = Query(description="Any day in the desired week; normalised to Monday"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealPlanResponse | None:
    """The plan for a week, or null when nothing has been planned for it yet.

    Null rather than 404: an unplanned week is a normal, expected state that
    the grid renders as empty, not a missing resource.
    """
    return await service.get_plan_for_week(
        db, current_user.household_id, current_user.id, day
    )


@router.post("", response_model=MealPlanResponse, status_code=http_status.HTTP_201_CREATED)
async def create_meal_plan(
    data: MealPlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealPlanResponse:
    """Get-or-create the plan for a week. Idempotent — re-posting the same week
    returns the existing plan rather than a second one."""
    await _require(
        db, current_user, "recipes", "create",
        "You don't have permission to plan meals.",
    )
    return await service.get_or_create_plan(
        db, current_user.household_id, current_user.id, data
    )


@router.patch("/{plan_id}", response_model=MealPlanResponse)
async def update_meal_plan(
    plan_id: uuid.UUID,
    data: MealPlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealPlanResponse:
    plan = await service.update_plan(
        db, plan_id, current_user.household_id, current_user.id, data
    )
    if plan is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Meal plan not found"
        )
    return plan


@router.delete("/{plan_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_meal_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_plan(
        db, plan_id, current_user.household_id, current_user.id
    )
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Meal plan not found"
        )


@router.post(
    "/{plan_id}/entries",
    response_model=MealPlanEntryResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def add_entry(
    plan_id: uuid.UUID,
    data: MealPlanEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealPlanEntryResponse:
    """Drop a recipe into a day+slot. Idempotent: the same recipe on the same
    cell twice returns the existing entry."""
    await _require(
        db, current_user, "recipes", "create",
        "You don't have permission to plan meals.",
    )
    entry, _created, error = await service.add_entry(
        db, plan_id, current_user.household_id, current_user.id, data
    )
    if entry is None:
        # "Not found" and "outside the week" are different mistakes and deserve
        # different answers — one is a bad id, the other a bad date.
        status = (
            http_status.HTTP_404_NOT_FOUND
            if error and "not found" in error.lower()
            else http_status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status, detail=error or "Could not plan meal")
    return entry


@router.patch("/{plan_id}/entries/{entry_id}", response_model=MealPlanEntryResponse)
async def update_entry(
    plan_id: uuid.UUID,
    entry_id: uuid.UUID,
    data: MealPlanEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MealPlanEntryResponse:
    entry = await service.update_entry(
        db, plan_id, entry_id, current_user.household_id, current_user.id, data
    )
    if entry is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Meal plan entry not found"
        )
    return entry


@router.delete(
    "/{plan_id}/entries/{entry_id}", status_code=http_status.HTTP_204_NO_CONTENT
)
async def remove_entry(
    plan_id: uuid.UUID,
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    removed = await service.remove_entry(
        db, plan_id, entry_id, current_user.household_id, current_user.id
    )
    if not removed:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Meal plan entry not found"
        )


@router.post("/{plan_id}/grocery-list", response_model=GenerateGroceryListResponse)
async def generate_grocery_list(
    plan_id: uuid.UUID,
    data: GenerateGroceryListRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GenerateGroceryListResponse:
    """Aggregate the week's planned recipes into a grocery list.

    Writes to the grocery domain, so it is gated on grocery permissions too.
    Safe to call twice: lines already on the target list un-checked are
    reported as `skipped` rather than added again.
    """
    await _require(
        db, current_user, "grocery", "create",
        "You don't have permission to create grocery lists.",
    )
    result, error = await service.generate_grocery_list(
        db, plan_id, current_user.household_id, current_user.id, data
    )
    if result is None:
        status = (
            http_status.HTTP_404_NOT_FOUND
            if error and "not found" in error.lower()
            else http_status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=status, detail=error or "Could not generate grocery list"
        )
    return result
