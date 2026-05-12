"""
Notes domain service.

All wikilink resolution happens here: on every save of content_md,
we re-scan for [[...]] patterns, resolve them against note titles in
the same household, and upsert/delete rows in note_backlinks.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from life_dashboard.domains.notes.models import Note, NoteBacklink, NoteTag
from life_dashboard.domains.notes.schemas import (
    BacklinkRef,
    NoteCreate,
    NoteListResponse,
    NoteResponse,
    NoteSummary,
    NoteUpdate,
    TagRef,
)
from life_dashboard.domains.tags.models import Tag

# ── Wikilink helpers ──────────────────────────────────────────────────────────

_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")


def _extract_wikilink_titles(markdown: str) -> list[str]:
    """Return all unique [[target]] titles found in a markdown string."""
    return list(dict.fromkeys(m.group(1).strip() for m in _WIKILINK_RE.finditer(markdown)))


async def _resolve_backlinks(
    db: AsyncSession,
    source: Note,
    household_id: uuid.UUID,
) -> None:
    """
    Re-resolve all [[wikilinks]] in source.content_md and sync the
    note_backlinks table for this source note.
    """
    # Delete existing outgoing links from this source — we'll re-add them.
    await db.execute(
        delete(NoteBacklink).where(NoteBacklink.source_note_id == source.id)
    )

    if not source.content_md:
        return

    titles = _extract_wikilink_titles(source.content_md)
    if not titles:
        return

    # Resolve titles → note IDs (case-insensitive ILIKE per title)
    title_to_note: dict[str, Note] = {}
    for title in titles:
        result = await db.execute(
            select(Note).where(
                Note.household_id == household_id,
                Note.id != source.id,
                Note.archived_at.is_(None),
                func.lower(Note.title) == title.lower(),
            )
        )
        note = result.scalar_one_or_none()
        if note:
            title_to_note[title.lower()] = note

    # Insert resolved backlinks
    for title in titles:
        target = title_to_note.get(title.lower())
        if target:
            db.add(NoteBacklink(
                source_note_id=source.id,
                target_note_id=target.id,
                alias=title,
            ))


# ── Serialisation helpers ─────────────────────────────────────────────────────

async def _load_note_response(db: AsyncSession, note: Note) -> NoteResponse:
    """Load a Note with tags + incoming backlinks and build the response schema."""
    # Load tags
    tag_result = await db.execute(
        select(NoteTag, Tag)
        .join(Tag, NoteTag.tag_id == Tag.id)
        .where(NoteTag.note_id == note.id)
    )
    tag_rows = tag_result.all()

    # Load incoming backlinks (notes that mention THIS note)
    bl_result = await db.execute(
        select(NoteBacklink, Note)
        .join(Note, NoteBacklink.source_note_id == Note.id)
        .where(NoteBacklink.target_note_id == note.id)
    )
    bl_rows = bl_result.all()

    return NoteResponse(
        id=note.id,
        title=note.title,
        content_md=note.content_md,
        content_json=note.content_json,
        archived_at=note.archived_at,
        created_at=note.created_at,
        updated_at=note.updated_at,
        tags=[TagRef(id=tag.id, name=tag.name, color=tag.color) for _, tag in tag_rows],
        backlinks=[
            BacklinkRef(id=src.id, title=src.title, alias=bl.alias)
            for bl, src in bl_rows
        ],
    )


# ── Service functions ─────────────────────────────────────────────────────────

async def list_notes(
    db: AsyncSession,
    household_id: uuid.UUID,
    include_archived: bool = False,
    tag_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> NoteListResponse:
    stmt = select(Note).where(Note.household_id == household_id)

    if not include_archived:
        stmt = stmt.where(Note.archived_at.is_(None))

    if tag_id:
        stmt = stmt.where(
            Note.id.in_(select(NoteTag.note_id).where(NoteTag.tag_id == tag_id))
        )

    if collection_id is not None:
        stmt = stmt.where(Note.collection_id == collection_id)

    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(Note.title.ilike(pattern) | Note.content_md.ilike(pattern))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(Note.updated_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    return NoteListResponse(
        items=[NoteSummary.model_validate(n) for n in rows],
        total=total,
    )


async def get_note(
    db: AsyncSession,
    note_id: uuid.UUID,
    household_id: uuid.UUID,
) -> NoteResponse | None:
    result = await db.execute(
        select(Note).where(Note.id == note_id, Note.household_id == household_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        return None
    return await _load_note_response(db, note)


async def create_note(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: NoteCreate,
) -> NoteResponse:
    note = Note(
        household_id=household_id,
        created_by_user_id=user_id,
        title=data.title,
        content_md=data.content_md,
        content_json=data.content_json,
        collection_id=data.collection_id,
    )
    db.add(note)
    await db.flush()  # Get note.id

    # Tags
    for tag_id in data.tag_ids:
        db.add(NoteTag(note_id=note.id, tag_id=tag_id))

    # Resolve wikilinks
    await _resolve_backlinks(db, note, household_id)

    await db.commit()
    await db.refresh(note)
    return await _load_note_response(db, note)


async def update_note(
    db: AsyncSession,
    note_id: uuid.UUID,
    household_id: uuid.UUID,
    data: NoteUpdate,
) -> NoteResponse | None:
    result = await db.execute(
        select(Note).where(Note.id == note_id, Note.household_id == household_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        return None

    updated_fields = data.model_fields_set
    if "title" in updated_fields and data.title is not None:
        note.title = data.title
    if "content_md" in updated_fields:
        note.content_md = data.content_md
    if "content_json" in updated_fields:
        note.content_json = data.content_json
    if "collection_id" in updated_fields:
        note.collection_id = data.collection_id

    note.updated_at = datetime.now(tz=timezone.utc)

    # Re-sync tags if provided
    if "tag_ids" in updated_fields and data.tag_ids is not None:
        await db.execute(delete(NoteTag).where(NoteTag.note_id == note.id))
        for tag_id in data.tag_ids:
            db.add(NoteTag(note_id=note.id, tag_id=tag_id))

    # Re-resolve backlinks whenever content changes
    if "content_md" in updated_fields or "title" in updated_fields:
        await _resolve_backlinks(db, note, household_id)

    await db.commit()
    await db.refresh(note)
    return await _load_note_response(db, note)


async def archive_note(
    db: AsyncSession,
    note_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Note).where(Note.id == note_id, Note.household_id == household_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        return False
    note.archived_at = datetime.now(tz=timezone.utc)
    await db.commit()
    return True


async def delete_note(
    db: AsyncSession,
    note_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Note).where(Note.id == note_id, Note.household_id == household_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        return False
    await db.delete(note)
    await db.commit()
    return True


async def delete_all_notes(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> int:
    """Delete every note belonging to this household. Returns the count deleted."""
    result = await db.execute(
        delete(Note)
        .where(Note.household_id == household_id)
        .returning(Note.id)
    )
    deleted = len(result.fetchall())
    await db.commit()
    return deleted
