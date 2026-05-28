"""
Collections domain service.

A Collection is a named, user-defined view over a domain (notes or documents)
with optional default tags, a default template, and an optional auto-create
rule for scheduled entry generation (e.g. daily journal entries).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
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

if TYPE_CHECKING:
    from life_dashboard.auth.models import User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_response(col: Collection) -> CollectionResponse:
    return CollectionResponse(
        id=col.id,
        household_id=col.household_id,
        created_by_user_id=col.created_by_user_id,
        name=col.name,
        icon=col.icon,
        domain=col.domain,  # type: ignore[arg-type]
        kind=col.kind,
        default_tags=[uuid.UUID(t) for t in (col.default_tags or [])],
        auto_create_rule=AutoCreateRule(**col.auto_create_rule) if col.auto_create_rule else None,
        show_in_nav=col.show_in_nav,
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


# Phase 2 of AI coach redesign. The default Journal collection is one of
# the "kind"-tagged collections the system seeds for every household, so
# both the signal extractor and the CBT-aware coach can find journal entries
# without relying on collection names. See docs/ai-coach-redesign.md.
_DEFAULT_JOURNAL_NAME = "Journal"
_DEFAULT_JOURNAL_ICON = "book-open"
_DEFAULT_JOURNAL_AUTO_CREATE = {
    "frequency": "daily",
    "title_template": "{{day_of_week}}, {{month}} {{day}}, {{year}}",
}


async def backfill_journal_kind(db: AsyncSession) -> dict[str, int]:
    """Idempotent startup hook — runs on every boot to make sure every
    household has a collection with kind='journal'.

    Why this exists separately from migration 0032: the migration's SQL
    backfill is Postgres-only because it uses native JSONB operators.
    Local SQLite dev installs get the new `kind` column from
    `_patch_sqlite_schema` but nothing populates it, leaving every
    existing collection at kind=NULL — which silently breaks the
    coach's narrative fetch and the journal signal extractor (both
    gate on kind='journal'). This function is the Python-side
    equivalent, safe to run on both backends.

    Three steps, each conservative:

    1) Tag existing notes-domain collections that look like journals
       (case-insensitive name match on 'journal', OR auto_create_rule
       with frequency='daily') with kind='journal' if they don't have a
       kind yet.
    2) For every household with no kind='journal' collection AND no
       collection that *looks* like a journal, insert a fresh one. We
       prefer not to insert when something journal-shaped already exists
       at a different name — the user gets to keep their naming.
    3) Returns counts for logging so a regression here is visible in the
       boot log without needing to inspect the DB.

    Always commits its own changes. Never raises — callers should still
    wrap in try/except for defense, but a single missing/malformed row
    will not crash boot.
    """
    from sqlalchemy import update
    from life_dashboard.auth.models import Household, HouseholdMembership

    counts = {"tagged": 0, "seeded": 0, "skipped": 0}

    try:
        # Step 1 — tag heuristically.
        candidates = (await db.execute(
            select(Collection).where(
                Collection.kind.is_(None),
                Collection.domain == "notes",
            )
        )).scalars().all()

        for col in candidates:
            looks_like_journal = False
            if (col.name or "").strip().lower() == "journal":
                looks_like_journal = True
            elif isinstance(col.auto_create_rule, dict) and (
                col.auto_create_rule.get("frequency") == "daily"
            ):
                looks_like_journal = True
            if looks_like_journal:
                col.kind = "journal"
                counts["tagged"] += 1

        # Step 2 — seed for households still missing one.
        household_ids = [
            hid for (hid,) in (await db.execute(select(Household.id))).all()
        ]
        for household_id in household_ids:
            # Already has a kind='journal' collection (either pre-existing,
            # or just tagged above)?
            has_one = (await db.execute(
                select(Collection.id).where(
                    Collection.household_id == household_id,
                    Collection.kind == "journal",
                )
                .limit(1)
            )).first()
            if has_one is not None:
                counts["skipped"] += 1
                continue

            # Pick the household's earliest member to attribute the seed to.
            owner_id = (await db.execute(
                select(HouseholdMembership.user_id)
                .where(HouseholdMembership.household_id == household_id)
                .order_by(HouseholdMembership.joined_at.asc())
                .limit(1)
            )).scalar_one_or_none()
            # owner_id may legitimately be None for orphan households —
            # the collection accepts NULL created_by_user_id.

            col = Collection(
                household_id=household_id,
                created_by_user_id=owner_id,
                name=_DEFAULT_JOURNAL_NAME,
                icon=_DEFAULT_JOURNAL_ICON,
                domain="notes",
                kind="journal",
                default_tags=[],
                auto_create_rule=_DEFAULT_JOURNAL_AUTO_CREATE,
                show_in_nav=True,
                sort_order=0,
            )
            db.add(col)
            counts["seeded"] += 1

        if counts["tagged"] > 0 or counts["seeded"] > 0:
            await db.commit()
    except Exception:
        # Caller logs the exception via their own except handler.
        await db.rollback()
        raise

    return counts


async def seed_default_journal_collection(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> CollectionResponse:
    """Idempotent: return the household's journal-kind collection, creating
    one if it doesn't exist yet.

    Called during household bootstrap (auth/setup signup) and on demand from
    the per-user upgrade path. Mirrors seed_system_project.
    """
    existing = (await db.execute(
        select(Collection).where(
            Collection.household_id == household_id,
            Collection.kind == "journal",
        )
    )).scalar_one_or_none()
    if existing:
        return _to_response(existing)

    col = Collection(
        household_id=household_id,
        created_by_user_id=user_id,
        name=_DEFAULT_JOURNAL_NAME,
        icon=_DEFAULT_JOURNAL_ICON,
        domain="notes",
        kind="journal",
        default_tags=[],
        auto_create_rule=_DEFAULT_JOURNAL_AUTO_CREATE,
        show_in_nav=True,
        sort_order=0,
    )
    db.add(col)
    await db.commit()
    await db.refresh(col)
    return _to_response(col)


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
        auto_create_rule=data.auto_create_rule.model_dump() if data.auto_create_rule else None,
        show_in_nav=data.show_in_nav,
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
    if "auto_create_rule" in updated:
        col.auto_create_rule = data.auto_create_rule.model_dump() if data.auto_create_rule else None
    if "show_in_nav" in updated and data.show_in_nav is not None:
        col.show_in_nav = data.show_in_nav
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
    migrate_to_collection_id: uuid.UUID | None = None,
) -> bool:
    """
    Delete a collection.

    If migrate_to_collection_id is provided, all notes and documents belonging
    to the collection are re-assigned to that target collection before deletion.
    If None, entries are deleted along with the collection (via CASCADE).

    Returns False if the collection does not exist.
    """
    result = await db.execute(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.household_id == household_id,
        )
    )
    col = result.scalar_one_or_none()
    if not col:
        return False

    if migrate_to_collection_id is not None:
        # Validate the destination collection exists in the same household
        dest_result = await db.execute(
            select(Collection).where(
                Collection.id == migrate_to_collection_id,
                Collection.household_id == household_id,
            )
        )
        dest = dest_result.scalar_one_or_none()
        if not dest:
            return False  # caller should surface a 404 with a clear message

        from life_dashboard.domains.notes.models import Note
        from life_dashboard.domains.documents.models import Document

        await db.execute(
            update(Note)
            .where(Note.collection_id == collection_id)
            .values(collection_id=migrate_to_collection_id)
        )
        await db.execute(
            update(Document)
            .where(Document.collection_id == collection_id)
            .values(collection_id=migrate_to_collection_id)
        )

    await db.delete(col)
    await db.commit()
    return True


# ── Auto-create (ensure-today) ────────────────────────────────────────────────

async def ensure_today_entry(
    db: AsyncSession,
    collection_id: uuid.UUID,
    household_id: uuid.UUID,
    user: "User",
) -> EnsureTodayResponse | None:
    """
    For collections with an auto_create_rule, ensure an entry for today exists.

    Resolves the entry title using {{variable}} syntax and the user's locale
    settings. Copies content from the collection's default template if one is
    assigned. Idempotent — returns the existing entry if today's title already
    exists.

    Returns None if the collection doesn't exist or has no auto_create_rule.
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

    from life_dashboard.domains.templates.service import get_default_template
    from life_dashboard.domains.templates.variables import resolve_variables

    rule = AutoCreateRule(**col.auto_create_rule)
    today_title = resolve_variables(rule.title_template, user)

    # Load the default template (if assigned)
    default_template = await get_default_template(db, col.id)

    if col.domain == "notes":
        return await _ensure_today_note(
            db, col, today_title, default_template, household_id, user
        )
    else:
        return await _ensure_today_document(
            db, col, today_title, default_template, household_id, user
        )


def _today_window(user: "User") -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) bracketing today in the user's local timezone."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(user.timezone) if user.timezone else timezone.utc
    except (ImportError, KeyError):
        tz = timezone.utc

    now_local = datetime.now(tz=tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


async def _ensure_today_note(
    db: AsyncSession,
    col: Collection,
    today_title: str,
    template: object | None,
    household_id: uuid.UUID,
    user: "User",
) -> EnsureTodayResponse:
    from life_dashboard.domains.notes.models import Note, NoteTag

    # Idempotency: return existing entry if one was created today (in user's tz)
    # regardless of its title — prevents duplicates when titles mismatch or the
    # user renamed their entry.
    start_utc, end_utc = _today_window(user)
    stmt = select(Note).where(
        Note.household_id == household_id,
        Note.collection_id == col.id,
        Note.archived_at.is_(None),
        Note.created_at >= start_utc,
        Note.created_at < end_utc,
    ).order_by(Note.created_at.asc()).limit(1)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return EnsureTodayResponse(created=False, item_id=existing.id, item_domain="notes")

    # Copy content from the default template if one is assigned
    content_md: str | None = None
    content_json: object | None = None
    if template is not None:
        content_md = getattr(template, "content_md", None)
        content_json = getattr(template, "content_json", None)

    note = Note(
        household_id=household_id,
        created_by_user_id=user.id,
        collection_id=col.id,
        title=today_title,
        content_md=content_md,
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
    template: object | None,
    household_id: uuid.UUID,
    user: "User",
) -> EnsureTodayResponse:
    from life_dashboard.domains.documents.models import Document
    import re

    # Idempotency: return existing entry if one was created today (in user's tz)
    start_utc, end_utc = _today_window(user)
    stmt = select(Document).where(
        Document.household_id == household_id,
        Document.collection_id == col.id,
        Document.archived_at.is_(None),
        Document.created_at >= start_utc,
        Document.created_at < end_utc,
    ).order_by(Document.created_at.asc()).limit(1)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return EnsureTodayResponse(created=False, item_id=existing.id, item_domain="documents")

    # Copy content from the default template if one is assigned
    editor_json: object | None = None
    if template is not None:
        editor_json = getattr(template, "content_json", None)

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
        created_by_user_id=user.id,
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
