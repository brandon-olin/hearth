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
from life_dashboard.domains.documents.models import Document
from life_dashboard.domains.documents.schemas import (
    DocumentChildrenResponse,
    DocumentCreate,
    DocumentImportRequest,
    DocumentImportResponse,
    DocumentResponse,
    DocumentSearchResponse,
    DocumentTreeResponse,
    DocumentUpdate,
)
from life_dashboard.domains.documents import service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "/bulk-import",
    response_model=DocumentImportResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def import_documents(
    data: DocumentImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentImportResponse:
    """Bulk-create documents from an external source (e.g. a Notion export).

    The client assigns temporary string IDs (client_id / client_parent_id) to
    express hierarchy. The server resolves them to real UUIDs and persists the
    pages in topological order.
    """
    perms = await load_household_permissions(db, current_user.household_id)
    if not check_permission(perms, "documents", "create", current_user.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to create documents.",
        )
    return await service.bulk_import_documents(
        db, current_user.household_id, current_user.id, data
    )


@router.delete("", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_all_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Hard-delete every document belonging to this household. Dev/testing only."""
    await service.delete_all_documents(db, current_user.household_id)


@router.get("", response_model=DocumentTreeResponse)
async def list_documents(
    include_archived: bool = Query(default=False),
    collection_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentTreeResponse:
    return await service.list_documents(
        db,
        current_user.household_id,
        user_id=current_user.id,
        include_archived=include_archived,
        collection_id=collection_id,
    )


@router.post("", response_model=DocumentResponse, status_code=http_status.HTTP_201_CREATED)
async def create_document(
    data: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    perms = await load_household_permissions(db, current_user.household_id)
    if not check_permission(perms, "documents", "create", current_user.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to create documents.",
        )
    return await service.create_document(db, current_user.household_id, current_user.id, data)


@router.get("/search", response_model=DocumentSearchResponse)
async def search_documents(
    q: str = Query(min_length=2, description="Search query (title and body)"),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentSearchResponse:
    """Full-text search across document titles and body (source_markdown).

    Results are ranked: title exact match > title contains > body contains.
    """
    return await service.search_documents(
        db, current_user.household_id, q, current_user.id, limit=limit, offset=offset
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentResponse:
    doc = await service.get_document(db, doc_id, current_user.household_id, user_id=current_user.id)
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
    creator_id = await get_item_creator(db, Document, doc_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "documents", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit others' documents.",
            )
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
    creator_id = await get_item_creator(db, Document, doc_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "documents", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to archive others' documents.",
            )
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
        db, doc_id, current_user.household_id, current_user.id, include_archived=include_archived
    )
    if result is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return result
