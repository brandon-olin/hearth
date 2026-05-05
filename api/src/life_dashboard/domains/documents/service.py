import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.documents.models import Document
from life_dashboard.domains.documents.schemas import (
    DocumentChildrenResponse,
    DocumentCreate,
    DocumentResponse,
    DocumentSummary,
    DocumentTreeResponse,
    DocumentUpdate,
)


# ── Slug helpers ──────────────────────────────────────────────────────────────

def _slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


async def _unique_slug(db: AsyncSession, household_id: uuid.UUID, base: str) -> str:
    """Appends a numeric suffix until the slug is unique within the household."""
    candidate = base
    suffix = 1
    while True:
        existing = (await db.execute(
            select(Document.id).where(
                Document.household_id == household_id,
                Document.slug == candidate,
            )
        )).scalar_one_or_none()
        if existing is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


# ── Response builders ─────────────────────────────────────────────────────────

def _to_response(doc: Document) -> DocumentResponse:
    return DocumentResponse.model_validate(doc)


def _to_summary(doc: Document) -> DocumentSummary:
    return DocumentSummary.model_validate(doc)


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_document(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: DocumentCreate,
) -> DocumentResponse:
    slug = await _unique_slug(db, household_id, _slugify(data.title))
    doc = Document(
        household_id=household_id,
        created_by_user_id=user_id,
        parent_id=data.parent_id,
        title=data.title,
        slug=slug,
        description=data.description,
        kind=data.kind,
        source_markdown=data.source_markdown,
        editor_json=data.editor_json,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return _to_response(doc)


async def get_document(
    db: AsyncSession,
    doc_id: uuid.UUID,
    household_id: uuid.UUID,
) -> DocumentResponse | None:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.household_id == household_id)
    )
    doc = result.scalar_one_or_none()
    return _to_response(doc) if doc else None


async def list_documents(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> DocumentTreeResponse:
    """Returns all documents for the household as a flat list.

    The client assembles the tree from parent_id. Returning flat avoids
    recursive queries and keeps the service layer simple.
    """
    query = select(Document).where(Document.household_id == household_id)
    if not include_archived:
        query = query.where(Document.archived_at.is_(None))
    query = query.order_by(Document.title.asc())

    docs = list((await db.execute(query)).scalars().all())
    return DocumentTreeResponse(
        items=[_to_summary(d) for d in docs],
        total=len(docs),
    )


async def update_document(
    db: AsyncSession,
    doc_id: uuid.UUID,
    household_id: uuid.UUID,
    data: DocumentUpdate,
) -> DocumentResponse | None:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.household_id == household_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        return None

    sent = data.model_fields_set

    # Reslug when title changes, preserving uniqueness.
    if "title" in sent and data.title is not None:
        doc.title = data.title
        doc.slug = await _unique_slug(db, household_id, _slugify(data.title))

    for field in ("parent_id", "description", "kind"):
        if field in sent:
            setattr(doc, field, getattr(data, field))

    # Dual storage: both fields are always written together when either is sent.
    if "source_markdown" in sent or "editor_json" in sent:
        if "source_markdown" in sent:
            doc.source_markdown = data.source_markdown
        if "editor_json" in sent:
            doc.editor_json = data.editor_json

    await db.commit()
    await db.refresh(doc)
    return _to_response(doc)


async def archive_document(
    db: AsyncSession,
    doc_id: uuid.UUID,
    household_id: uuid.UUID,
) -> DocumentResponse | None:
    """Soft-delete: sets archived_at. Hard delete is not exposed."""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.household_id == household_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        return None
    doc.archived_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(doc)
    return _to_response(doc)


async def get_children(
    db: AsyncSession,
    doc_id: uuid.UUID,
    household_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> DocumentChildrenResponse | None:
    """Returns direct children of a document.

    Returns None when the parent doesn't exist or belongs to a different household.
    """
    parent = (await db.execute(
        select(Document.id).where(Document.id == doc_id, Document.household_id == household_id)
    )).scalar_one_or_none()
    if parent is None:
        return None

    query = select(Document).where(
        Document.parent_id == doc_id,
        Document.household_id == household_id,
    )
    if not include_archived:
        query = query.where(Document.archived_at.is_(None))
    query = query.order_by(Document.title.asc())

    children = list((await db.execute(query)).scalars().all())
    return DocumentChildrenResponse(items=[_to_summary(c) for c in children])
