import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.notes import service
from life_dashboard.domains.notes.schemas import (
    NoteCreate,
    NoteListResponse,
    NoteResponse,
    NoteUpdate,
)

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=NoteListResponse)
async def list_notes(
    include_archived: bool = False,
    tag_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    q: str | None = Query(None, description="Full-text filter on title and content"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_notes(
        db,
        household_id=current_user.household_id,
        include_archived=include_archived,
        tag_id=tag_id,
        collection_id=collection_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=NoteResponse, status_code=201)
async def create_note(
    data: NoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.create_note(
        db,
        household_id=current_user.household_id,
        user_id=current_user.id,
        data=data,
    )


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await service.get_note(db, note_id=note_id, household_id=current_user.household_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: uuid.UUID,
    data: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = await service.update_note(
        db,
        note_id=note_id,
        household_id=current_user.household_id,
        data=data,
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.delete("", status_code=200)
async def delete_all_notes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete all notes for the current household."""
    count = await service.delete_all_notes(db, household_id=current_user.household_id)
    return {"deleted": count}


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted = await service.delete_note(
        db, note_id=note_id, household_id=current_user.household_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
