import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.templates import service
from life_dashboard.domains.templates.schemas import (
    CollectionTemplateAssign,
    CollectionTemplateListResponse,
    CollectionTemplateResponse,
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)

router = APIRouter(tags=["templates"])


# ── Template CRUD ─────────────────────────────────────────────────────────────

@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(
    domain: str | None = Query(None, description="Filter by domain: 'notes' or 'documents'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all templates visible to the current user:
    household-scoped templates for their household, plus their own user-scoped templates.
    """
    return await service.list_templates(
        db,
        household_id=current_user.household_id,
        user_id=current_user.id,
        domain=domain,
    )


@router.post("/templates", response_model=TemplateResponse, status_code=201)
async def create_template(
    data: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.create_template(
        db,
        household_id=current_user.household_id,
        user_id=current_user.id,
        data=data,
    )


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    t = await service.get_template(
        db,
        template_id=template_id,
        household_id=current_user.household_id,
        user_id=current_user.id,
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return t


@router.patch("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    data: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    t = await service.update_template(
        db,
        template_id=template_id,
        household_id=current_user.household_id,
        user_id=current_user.id,
        data=data,
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return t


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = await service.delete_template(
        db,
        template_id=template_id,
        household_id=current_user.household_id,
        user_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")


# ── Collection-template assignment (mounted under /collections) ───────────────

collections_template_router = APIRouter(tags=["templates"])


@collections_template_router.get(
    "/collections/{collection_id}/templates",
    response_model=CollectionTemplateListResponse,
)
async def list_collection_templates(
    collection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all templates assigned to a collection."""
    return await service.list_collection_templates(
        db,
        collection_id=collection_id,
        household_id=current_user.household_id,
        user_id=current_user.id,
    )


@collections_template_router.post(
    "/collections/{collection_id}/templates",
    response_model=CollectionTemplateResponse,
    status_code=201,
)
async def assign_template(
    collection_id: uuid.UUID,
    data: CollectionTemplateAssign,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Assign a template to a collection.
    If is_default=True, any existing default is cleared first.
    """
    result = await service.assign_template_to_collection(
        db,
        collection_id=collection_id,
        household_id=current_user.household_id,
        user_id=current_user.id,
        data=data,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result


@collections_template_router.delete(
    "/collections/{collection_id}/templates/{template_id}",
    status_code=204,
)
async def remove_template(
    collection_id: uuid.UUID,
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a template assignment from a collection."""
    deleted = await service.remove_template_from_collection(
        db,
        collection_id=collection_id,
        template_id=template_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Assignment not found")


@collections_template_router.patch(
    "/collections/{collection_id}/templates/{template_id}/default",
    status_code=200,
)
async def set_default_template(
    collection_id: uuid.UUID,
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a template as the default for this collection (clears any existing default)."""
    ok = await service.set_default_template(
        db,
        collection_id=collection_id,
        template_id=template_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return {"ok": True}
