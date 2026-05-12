"""
Collections domain service.

A Collection is a named, user-defined view over a domain (notes or documents)
with optional default tags, a default template, and an optional auto-create
rule for scheduled entry generation (e.g. daily journal entries).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.collections.models import Collection
from life_dashboard.domains.collections.schemas import (
    AutoCreateRule,
    CollectionCreate,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdate,
    EnsureTodayResponse,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_response(col: Collection) -> CollectionResponse:
    return CollectionResponse(
        id=col.id,
        household_id=col.household_id,
        created_by_user_id=col.created_by_user_id,
        name=col.name,
        icon=col.icon,
        domain=col.domain,  # type: ignore[arg-type]
        default_tags=[uuid.UUID(t) for t in (col.default_tags or [])],
        default_template_id=col.default_template_id,
        auto_create_rule=AutoCreateRule(**col.auto_create_rule) if col.auto_create_rule else None,
        sort_order=col.sort_order,
        created_at=col.created_at,
        updated_at=col.updated_at,
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def list_collections(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> CollectionListResponse:
    stmt = (
        select(Collection)
        .where(Collection.household_id == household_id)
        .order_by(Collection.sort_order.asc(), Collection.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return CollectionListResponse(
        items=[_to_response(c) for c in rows],
        total=len(rows),
    )


async def get_collection(
    db: AsyncSession,
    collection_id: uuid.UUID,
    household_id: uuid.UUID,
) -> CollectionResponse | None:
    result = await db.execute(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.household_id == household_id,
        )
    )
    col = result.scalar_one_or_none()
    return _to_response(col) if col else None


async def create_collection(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CollectionCreate,
) -> CollectionResponse:
    col = Collection(
        household_id=household_id,
        created_by_user_id=user_id,
        name=data.name,
        icon=data.icon,
        domain=data.domain,
        default_tags=[str(t) for t in data.default_tags],
        default_template_id=data.default_template_id,
        auto_create_rule=data.auto_create_rule.model_dump() if data.auto_create_rule else None,
        sort_order=data.sort_order,
    )
    db.add(col)
    await db.commit()
    await db.refresh(col)
    return _to_response(col)


async def update_collection(
    db: AsyncSession,
    collection_id: uuid.UUID,
    household_id: uuid.UUID,
    data: CollectionUpdate,
) -> CollectionResponse | None:
    result = await db.execute(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.household_id == household_id,
        )
    )
    col = result.scalar_one_or_none()
    if not col:
        return None

    updated = data.model_fields_set
    if "name" in updated and data.name is not None:
        col.name = data.name
    if "icon" in updated:
        col.icon = data.icon
    if "default_tags" in updated and data.default_tags is not None:
        col.default_tags = [str(t) for t in data.default_tags]
    if "default_template_id" in updated:
        col.default_template_id = data.default_template_id
    if "auto_create_rule" in updated:
        col.auto_create_rule = data.auto_create_rule.model_dump() if data.auto_create_rule else None
    if "sort_order" in updated and data.sort_order is not None:
        col.sort_order = data.sort_order

    col.updated_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(col)
    return _to_response(col)


async def delete_collection(
    db: AsyncSession,
    collection_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.household_id == household_id,
        )
    )
    col = result.scalar_one_or_none()
    if not col:
        return False
    await db.delete(col)
    await db.commit()
    return True


# ── Auto-create (ensure-today) ────────────────────────────────────────────────

async def ensure_today_entry(
    db: AsyncSession,
    collection_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> EnsureTodayResponse | None:
    """
    For collections with an auto_create_rule, ensure that an entry for today
    exists in the collection's domain, creating one if it doesn't.

    Returns None if the collection doesn't exist or has no auto_create_rule.
    The title is generated by strftime(title_template, today).
    """
    result = await db.execute(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.household_id == household_id,
        )
    )
    col = result.scalar_one_or_none()
    if not col or not col.auto_create_rule:
        return None

    rule = AutoCreateRule(**col.auto_create_rule)
    today = date.today()
    today_title = today.strftime(rule.title_template)

    if col.domain == "notes":
        return await _ensure_today_note(db, col, today_title, household_id, user_id)
    else:
        return await _ensure_today_document(db, col, today_title, household_id, user_id)


async def _ensure_today_note(
    db: AsyncSession,
    col: Collection,
    today_title: str,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> EnsureTodayResponse:
    from life_dashboard.domains.notes.models import Note, NoteTag

    # Check for an existing entry with today's title in this collection
    stmt = select(Note).where(
        Note.household_id == household_id,
        Note.collection_id == col.id,
        Note.title == today_title,
        Note.archived_at.is_(None),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return EnsureTodayResponse(created=False, item_id=existing.id, item_domain="notes")

    # Resolve template content if configured
    content_json = None
    if col.default_template_id:
        from life_dashboard.domains.documents.models import Document
        tmpl_result = await db.execute(
            select(Document).where(
                Document.id == col.default_template_id,
                Document.household_id == household_id,
            )
        )
        tmpl = tmpl_result.scalar_one_or_none()
        if tmpl:
            content_json = tmpl.editor_json

    note = Note(
        household_id=household_id,
        created_by_user_id=user_id,
        collection_id=col.id,
        title=today_title,
        content_json=content_json,
    )
    db.add(note)
    await db.flush()

    for tag_id_str in (col.default_tags or []):
        db.add(NoteTag(note_id=note.id, tag_id=uuid.UUID(tag_id_str)))

    await db.commit()
    await db.refresh(note)
    return EnsureTodayResponse(created=True, item_id=note.id, item_domain="notes")


async def _ensure_today_document(
    db: AsyncSession,
    col: Collection,
    today_title: str,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> EnsureTodayResponse:
    from life_dashboard.domains.documents.models import Document
    import re

    # Check for an existing entry with today's title in this collection
    stmt = select(Document).where(
        Document.household_id == household_id,
        Document.collection_id == col.id,
        Document.title == today_title,
        Document.archived_at.is_(None),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return EnsureTodayResponse(created=False, item_id=existing.id, item_domain="documents")

    # Resolve template content if configured
    editor_json = None
    if col.default_template_id:
        tmpl_result = await db.execute(
            select(Document).where(
                Document.id == col.default_template_id,
                Document.household_id == household_id,
            )
        )
        tmpl = tmpl_result.scalar_one_or_none()
        if tmpl:
            editor_json = tmpl.editor_json

    # Generate a slug from the title
    slug_base = re.sub(r"[^\w\s-]", "", today_title.lower())
    slug_base = re.sub(r"[\s_-]+", "-", slug_base).strip("-")

    # Ensure slug uniqueness within the household
    slug = slug_base
    counter = 1
    while True:
        conflict = await db.execute(
            select(Document).where(
                Document.household_id == household_id,
                Document.slug == slug,
            )
        )
        if not conflict.scalar_one_or_none():
            break
        slug = f"{slug_base}-{counter}"
        counter += 1

    doc = Document(
        household_id=household_id,
        created_by_user_id=user_id,
        collection_id=col.id,
        title=today_title,
        slug=slug,
        kind="page",
        editor_json=editor_json,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return EnsureTodayResponse(created=True, item_id=doc.id, item_domain="documents")
