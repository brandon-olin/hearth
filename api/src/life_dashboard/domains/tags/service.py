import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.tags.models import Tag
from life_dashboard.domains.tags.schemas import (
    TagCreate,
    TagListResponse,
    TagResponse,
    TagUpdate,
)


async def create_tag(
    db: AsyncSession,
    household_id: uuid.UUID,
    data: TagCreate,
) -> TagResponse | None:
    """Returns None if a tag with the same name already exists in this household."""
    tag = Tag(
        household_id=household_id,
        name=data.name,
        color=data.color,
    )
    db.add(tag)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return None
    await db.refresh(tag)
    return TagResponse.model_validate(tag)


async def get_tag(
    db: AsyncSession,
    tag_id: uuid.UUID,
    household_id: uuid.UUID,
) -> TagResponse | None:
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.household_id == household_id)
    )
    tag = result.scalar_one_or_none()
    if tag is None:
        return None
    return TagResponse.model_validate(tag)


async def list_tags(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> TagListResponse:
    query = select(Tag).where(Tag.household_id == household_id)

    if search:
        query = query.where(Tag.name.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    tags = list(
        (await db.execute(
            query.order_by(Tag.name.asc()).limit(limit).offset(offset)
        )).scalars().all()
    )

    return TagListResponse(
        items=[TagResponse.model_validate(t) for t in tags],
        total=total,
        limit=limit,
        offset=offset,
    )


async def update_tag(
    db: AsyncSession,
    tag_id: uuid.UUID,
    household_id: uuid.UUID,
    data: TagUpdate,
) -> TagResponse | None:
    """Returns None if not found. Raises 409 via IntegrityError if name conflicts."""
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.household_id == household_id)
    )
    tag = result.scalar_one_or_none()
    if tag is None:
        return None

    sent = data.model_fields_set
    if "name" in sent and data.name is not None:
        tag.name = data.name
    if "color" in sent:
        tag.color = data.color

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(tag)
    return TagResponse.model_validate(tag)


async def delete_tag(
    db: AsyncSession,
    tag_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.household_id == household_id)
    )
    tag = result.scalar_one_or_none()
    if tag is None:
        return False
    await db.delete(tag)
    await db.commit()
    return True
