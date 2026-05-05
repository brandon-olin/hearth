import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.domains.documents.schemas import (
    DocumentChildrenResponse,
    DocumentCreate,
    DocumentResponse,
    DocumentTreeResponse,
    DocumentUpdate,
)
from life_dashboard.domains.documents import service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=DocumentTreeResponse)
async def list_documents(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentTreeResponse:
    return await service.list_documents(
        db, current_user.household_id, include_archived=include_archived
    )


@router.post("", response_model=DocumentResponse, status_code=http_status.HTTP_201_CREATED)
async def create_document(
    data: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    return await service.create_document(db, current_user.household_id, current_user.id, data)


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    doc = await service.get_document(db, doc_id, current_user.household_id)
    if doc is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return doc


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    doc_id: uuid.UUID,
    data: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    doc = await service.update_document(db, doc_id, current_user.household_id, data)
    if doc is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return doc


@router.delete("/{doc_id}", response_model=DocumentResponse)
async def archive_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    """Soft-delete: sets archived_at. Returns the archived document."""
    doc = await service.archive_document(db, doc_id, current_user.household_id)
    if doc is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return doc


@router.get("/{doc_id}/children", response_model=DocumentChildrenResponse)
async def get_children(
    doc_id: uuid.UUID,
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentChildrenResponse:
    result = await service.get_children(
        db, doc_id, current_user.household_id, include_archived=include_archived
    )
    if result is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return result
