import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.recipes.schemas import (
    RecipeCreate,
    RecipeListResponse,
    RecipeResponse,
    RecipeUpdate,
)
from life_dashboard.domains.recipes import service

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.get("", response_model=RecipeListResponse)
async def list_recipes(
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecipeListResponse:
    return await service.list_recipes(
        db, current_user.household_id, search=search, limit=limit, offset=offset
    )


@router.get("/import", response_model=RecipeCreate)
async def import_recipe_preview(
    url: str = Query(..., min_length=8, description="Public URL of a recipe page with JSON-LD markup"),
    current_user: User = Depends(get_current_user),
) -> RecipeCreate:
    """
    Fetch a recipe page and return a pre-populated RecipeCreate from its
    Schema.org JSON-LD data.  Nothing is written to the database — the client
    should POST the returned payload to ``POST /recipes`` to save it.
    """
    import httpx
    from life_dashboard.domains.recipes.importer import (
        RecipeImportError,
        fetch_recipe_preview,
    )

    try:
        return await fetch_recipe_preview(url)
    except RecipeImportError as exc:
        raise HTTPException(status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"The page returned HTTP {exc.response.status_code}.",
        )
    except Exception:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failed to import recipe from that URL.",
        )


@router.get("/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecipeResponse:
    recipe = await service.get_recipe(db, recipe_id, current_user.household_id)
    if recipe is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return recipe


@router.post("", response_model=RecipeResponse, status_code=http_status.HTTP_201_CREATED)
async def create_recipe(
    data: RecipeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecipeResponse:
    return await service.create_recipe(db, current_user.household_id, current_user.id, data)


@router.patch("/{recipe_id}", response_model=RecipeResponse)
async def update_recipe(
    recipe_id: uuid.UUID,
    data: RecipeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecipeResponse:
    recipe = await service.update_recipe(db, recipe_id, current_user.household_id, data)
    if recipe is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return recipe


@router.delete("/{recipe_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_recipe(
    recipe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_recipe(db, recipe_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Recipe not found")


@router.put("/{recipe_id}/tags/{tag_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def add_tag(
    recipe_id: uuid.UUID,
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ok = await service.add_tag(db, recipe_id, tag_id, current_user.household_id)
    if not ok:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Recipe or tag not found"
        )


@router.delete("/{recipe_id}/tags/{tag_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def remove_tag(
    recipe_id: uuid.UUID,
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ok = await service.remove_tag(db, recipe_id, tag_id, current_user.household_id)
    if not ok:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Recipe not found")
