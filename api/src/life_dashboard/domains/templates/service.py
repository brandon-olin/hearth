"""
Templates domain service.

A Template is a reusable content blueprint for collection entries.
Templates are household-scoped by default; user-scoped templates are
private to their creator.

CollectionTemplate is the join between a Collection and its assigned
Templates. At most one entry per collection may be marked is_default=True.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.templates.models import CollectionTemplate, Template
from life_dashboard.domains.templates.schemas import (
    CollectionTemplateAssign,
    CollectionTemplateListResponse,
    CollectionTemplateResponse,
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _template_to_response(t: Template) -> TemplateResponse:
    return TemplateResponse(
        id=t.id,
        household_id=t.household_id,
        created_by_user_id=t.created_by_user_id,
        scope=t.scope,  # type: ignore[arg-type]
        name=t.name,
        description=t.description,
        domain=t.domain,  # type: ignore[arg-type]
        title_template=t.title_template,
        content_md=t.content_md,
        content_json=t.content_json,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _ct_to_response(ct: CollectionTemplate, template: Template) -> CollectionTemplateResponse:
    return CollectionTemplateResponse(
        id=ct.id,
        template_id=ct.template_id,
        collection_id=ct.collection_id,
        is_default=ct.is_default,
        created_at=ct.created_at,
        template=_template_to_response(template),
    )


# ── Template CRUD ─────────────────────────────────────────────────────────────

async def list_templates(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    domain: str | None = None,
) -> TemplateListResponse:
    """
    Return all templates visible to this user:
      - household-scoped templates for their household
      - user-scoped templates they created

    Optionally filter by domain ("notes" or "documents").
    """
    stmt = select(Template).where(
        # Household-scoped: any member can see these
        (
            (Template.household_id == household_id)
            & (Template.scope == "household")
        )
        |
        # User-scoped: only the creator sees these
        (
            (Template.household_id == household_id)
            & (Template.scope == "user")
            & (Template.created_by_user_id == user_id)
        )
    )
    if domain:
        stmt = stmt.where(Template.domain == domain)

    stmt = stmt.order_by(Template.name.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return TemplateListResponse(
        items=[_template_to_response(t) for t in rows],
        total=len(rows),
    )


async def get_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> TemplateResponse | None:
    """
    Fetch a single template if visible to this user.
    User-scoped templates are only returned to their creator.
    """
    result = await db.execute(
        select(Template).where(
            Template.id == template_id,
            Template.household_id == household_id,
        )
    )
    t = result.scalar_one_or_none()
    if not t:
        return None
    # Enforce user-scope privacy
    if t.scope == "user" and t.created_by_user_id != user_id:
        return None
    return _template_to_response(t)


async def create_template(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: TemplateCreate,
) -> TemplateResponse:
    t = Template(
        household_id=household_id,
        created_by_user_id=user_id,
        scope=data.scope,
        name=data.name,
        description=data.description,
        domain=data.domain,
        title_template=data.title_template,
        content_md=data.content_md,
        content_json=data.content_json,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _template_to_response(t)


async def update_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: TemplateUpdate,
) -> TemplateResponse | None:
    result = await db.execute(
        select(Template).where(
            Template.id == template_id,
            Template.household_id == household_id,
        )
    )
    t = result.scalar_one_or_none()
    if not t:
        return None
    if t.scope == "user" and t.created_by_user_id != user_id:
        return None  # 404 rather than 403 — don't leak existence of private templates

    updated = data.model_fields_set
    if "name" in updated and data.name is not None:
        t.name = data.name
    if "description" in updated:
        t.description = data.description
    if "scope" in updated and data.scope is not None:
        t.scope = data.scope
    if "title_template" in updated:
        t.title_template = data.title_template
    if "content_md" in updated:
        t.content_md = data.content_md
    if "content_json" in updated:
        t.content_json = data.content_json

    t.updated_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(t)
    return _template_to_response(t)


async def delete_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Template).where(
            Template.id == template_id,
            Template.household_id == household_id,
        )
    )
    t = result.scalar_one_or_none()
    if not t:
        return False
    if t.scope == "user" and t.created_by_user_id != user_id:
        return False
    await db.delete(t)
    await db.commit()
    return True


# ── Collection-template assignment ────────────────────────────────────────────

async def list_collection_templates(
    db: AsyncSession,
    collection_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> CollectionTemplateListResponse:
    """Return all templates assigned to a collection, with embedded template detail."""
    stmt = (
        select(CollectionTemplate, Template)
        .join(Template, CollectionTemplate.template_id == Template.id)
        .where(CollectionTemplate.collection_id == collection_id)
        # Enforce scope: household templates + user's own private templates
        .where(
            (Template.scope == "household")
            | (
                (Template.scope == "user")
                & (Template.created_by_user_id == user_id)
            )
        )
        .order_by(Template.name.asc())
    )
    rows = (await db.execute(stmt)).all()
    return CollectionTemplateListResponse(
        items=[_ct_to_response(ct, t) for ct, t in rows],
        total=len(rows),
    )


async def assign_template_to_collection(
    db: AsyncSession,
    collection_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CollectionTemplateAssign,
) -> CollectionTemplateResponse | None:
    """
    Assign a template to a collection.

    If is_default=True, clears is_default on any existing default first
    (only one default per collection is allowed).

    Returns None if the template doesn't exist or isn't accessible.
    """
    # Verify template exists and is accessible
    tmpl = await get_template(db, data.template_id, household_id, user_id)
    if not tmpl:
        return None

    # Check for an existing assignment — update rather than duplicate
    existing_result = await db.execute(
        select(CollectionTemplate).where(
            CollectionTemplate.collection_id == collection_id,
            CollectionTemplate.template_id == data.template_id,
        )
    )
    ct = existing_result.scalar_one_or_none()

    if data.is_default:
        await _clear_default(db, collection_id)

    if ct:
        ct.is_default = data.is_default
    else:
        ct = CollectionTemplate(
            collection_id=collection_id,
            template_id=data.template_id,
            is_default=data.is_default,
        )
        db.add(ct)

    await db.commit()
    await db.refresh(ct)

    # Reload the template for embedding in the response
    t_result = await db.execute(select(Template).where(Template.id == ct.template_id))
    t = t_result.scalar_one()
    return _ct_to_response(ct, t)


async def remove_template_from_collection(
    db: AsyncSession,
    collection_id: uuid.UUID,
    template_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(CollectionTemplate).where(
            CollectionTemplate.collection_id == collection_id,
            CollectionTemplate.template_id == template_id,
        )
    )
    ct = result.scalar_one_or_none()
    if not ct:
        return False
    await db.delete(ct)
    await db.commit()
    return True


async def set_default_template(
    db: AsyncSession,
    collection_id: uuid.UUID,
    template_id: uuid.UUID,
) -> bool:
    """Mark a specific assigned template as default, clearing any existing default."""
    result = await db.execute(
        select(CollectionTemplate).where(
            CollectionTemplate.collection_id == collection_id,
            CollectionTemplate.template_id == template_id,
        )
    )
    ct = result.scalar_one_or_none()
    if not ct:
        return False

    await _clear_default(db, collection_id)
    ct.is_default = True
    await db.commit()
    return True


async def get_default_template(
    db: AsyncSession,
    collection_id: uuid.UUID,
) -> Template | None:
    """Return the default Template for a collection, or None if none is set."""
    result = await db.execute(
        select(Template)
        .join(CollectionTemplate, CollectionTemplate.template_id == Template.id)
        .where(
            CollectionTemplate.collection_id == collection_id,
            CollectionTemplate.is_default.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _clear_default(db: AsyncSession, collection_id: uuid.UUID) -> None:
    """Clear is_default on all templates assigned to a collection."""
    result = await db.execute(
        select(CollectionTemplate).where(
            CollectionTemplate.collection_id == collection_id,
            CollectionTemplate.is_default.is_(True),
        )
    )
    for ct in result.scalars().all():
        ct.is_default = False
