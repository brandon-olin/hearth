import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.documents.models import Document
from life_dashboard.domains.documents.schemas import (
    DocumentChildrenResponse,
    DocumentCreate,
    DocumentImportRequest,
    DocumentImportResponse,
    DocumentImportResultItem,
    DocumentResponse,
    DocumentSearchResponse,
    DocumentSearchResult,
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


async def bulk_import_documents(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    request: DocumentImportRequest,
) -> DocumentImportResponse:
    """Create multiple documents in one request, preserving hierarchy.

    Items may arrive in any order; the function topologically sorts them so
    parents are always inserted before their children. client_id values are
    temporary browser-assigned strings; they are mapped to real DB UUIDs once
    each row is persisted.
    """
    items = request.items

    # ── Topological sort (Kahn's algorithm) ──────────────────────────────────
    # Build adjacency and in-degree from client IDs.
    client_ids = {item.client_id for item in items}
    children_of: dict[str, list[str]] = {cid: [] for cid in client_ids}
    in_degree: dict[str, int] = {cid: 0 for cid in client_ids}

    for item in items:
        if item.client_parent_id and item.client_parent_id in client_ids:
            children_of[item.client_parent_id].append(item.client_id)
            in_degree[item.client_id] += 1

    by_client_id = {item.client_id: item for item in items}
    queue = [cid for cid, deg in in_degree.items() if deg == 0]
    ordered: list[str] = []

    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for child_id in children_of[current]:
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                queue.append(child_id)

    # Any remaining items have circular parents — skip them gracefully.
    skipped_count = len(items) - len(ordered)

    # ── Insert in topological order ───────────────────────────────────────────
    client_to_db: dict[str, uuid.UUID] = {}
    # Track (client_id, doc) so we can return client_id in the response for
    # the browser to reconcile imported pages with pre-upload state.
    created_pairs: list[tuple[str, Document]] = []

    for client_id in ordered:
        item = by_client_id[client_id]

        # Resolve parent: use real DB UUID if parent was already inserted,
        # otherwise treat as root (parent outside the import set is not supported
        # client-side currently, but could be added later).
        parent_db_id: uuid.UUID | None = None
        if item.client_parent_id and item.client_parent_id in client_to_db:
            parent_db_id = client_to_db[item.client_parent_id]

        slug = await _unique_slug(db, household_id, _slugify(item.title))

        doc = Document(
            household_id=household_id,
            created_by_user_id=user_id,
            parent_id=parent_db_id,
            title=item.title,
            slug=slug,
            kind="page",
            source_markdown=item.source_markdown,
            editor_json=item.editor_json,
        )
        db.add(doc)
        await db.flush()  # Populate doc.id without committing.

        client_to_db[client_id] = doc.id
        created_pairs.append((client_id, doc))

    await db.commit()
    for _, doc in created_pairs:
        await db.refresh(doc)

    result_items = [
        DocumentImportResultItem(client_id=cid, **_to_summary(doc).model_dump())
        for cid, doc in created_pairs
    ]

    return DocumentImportResponse(
        created=len(created_pairs),
        skipped=skipped_count,
        items=result_items,
    )


async def delete_all_documents(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> None:
    """Hard-delete all documents for a household. Intended for dev/test resets."""
    await db.execute(
        delete(Document).where(Document.household_id == household_id)
    )
    await db.commit()


# ── Search ────────────────────────────────────────────────────────────────────

_SNIPPET_CONTEXT = 60  # characters of context around a body match


def _make_snippet(text: str, term: str) -> str:
    """Return a short excerpt around the first occurrence of term in text."""
    pos = text.lower().find(term.lower())
    if pos < 0:
        return text[:_SNIPPET_CONTEXT * 2].strip()
    start = max(0, pos - _SNIPPET_CONTEXT)
    end = min(len(text), pos + len(term) + _SNIPPET_CONTEXT)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


async def search_documents(
    db: AsyncSession,
    household_id: uuid.UUID,
    q: str,
    *,
    limit: int = 20,
    offset: int = 0,
) -> DocumentSearchResponse:
    """Search documents by title and body (source_markdown).

    Priority order:
      1. Title exact match (case-insensitive)
      2. Title contains match
      3. Body (source_markdown) contains match

    Returns up to limit+1 items so the caller can determine has_more.
    """
    q_lower = q.lower()
    q_like = f"%{q}%"

    stmt = (
        select(Document)
        .where(
            Document.household_id == household_id,
            Document.archived_at.is_(None),
            or_(
                Document.title.ilike(q_like),
                Document.source_markdown.ilike(q_like),
            ),
        )
        .order_by(
            case(
                (func.lower(Document.title) == q_lower, 1),
                (Document.title.ilike(q_like), 2),
                else_=3,
            ),
            Document.title.asc(),
        )
        .limit(limit + 1)
        .offset(offset)
    )

    docs = list((await db.execute(stmt)).scalars().all())
    has_more = len(docs) > limit
    docs = docs[:limit]

    items: list[DocumentSearchResult] = []
    for doc in docs:
        title_match = q_lower in (doc.title or "").lower()
        match_type = "title" if title_match else "body"
        snippet: str | None = None
        if match_type == "body" and doc.source_markdown:
            snippet = _make_snippet(doc.source_markdown, q)
        items.append(
            DocumentSearchResult(
                match_type=match_type,
                snippet=snippet,
                **_to_summary(doc).model_dump(),
            )
        )

    return DocumentSearchResponse(items=items, has_more=has_more)
