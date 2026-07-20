"""Superset-group invariants shared by templates and sessions (workouts-001).

A superset groups several exercise slots that are performed together, one round
at a time. The rules are identical whether the slots live in a template
(``TemplateExercise``) or a logged session (``SessionExercise``):

* A group has **2–5 members** within the same parent (template or session).
* Adding a 6th member is rejected — the service raises :class:`SupersetError`,
  which the router surfaces as ``400``.
* Removing a member that would leave a **lone** member dissolves the group:
  the remaining member's ``superset_group_id`` is cleared so a "superset of one"
  never persists.

The functions take the ORM model class plus the parent-scoping WHERE clause, so
one implementation serves both tables.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

MIN_SUPERSET_MEMBERS = 2
MAX_SUPERSET_MEMBERS = 5


class SupersetError(Exception):
    """A superset-group operation violated the 2–5 member rule. Routers map this
    to HTTP 400; the message is safe to show the caller."""


async def count_group_members(
    db: AsyncSession,
    model: Any,
    parent_clause: Any,
    group_id: uuid.UUID,
    *,
    exclude_id: uuid.UUID | None = None,
) -> int:
    """Number of rows in ``group_id`` within one parent, optionally excluding a
    row (used when moving/updating an existing member)."""
    stmt = (
        select(func.count())
        .select_from(model)
        .where(parent_clause, model.superset_group_id == group_id)
    )
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return (await db.execute(stmt)).scalar_one()


async def assert_capacity_for_join(
    db: AsyncSession,
    model: Any,
    parent_clause: Any,
    group_id: uuid.UUID,
    *,
    exclude_id: uuid.UUID | None = None,
    incoming: int = 1,
) -> None:
    """Raise :class:`SupersetError` if adding ``incoming`` members to ``group_id``
    would push it past :data:`MAX_SUPERSET_MEMBERS`."""
    current = await count_group_members(
        db, model, parent_clause, group_id, exclude_id=exclude_id
    )
    if current + incoming > MAX_SUPERSET_MEMBERS:
        raise SupersetError(
            f"A superset can hold at most {MAX_SUPERSET_MEMBERS} exercises; "
            f"this group already has {current}."
        )


async def dissolve_if_orphaned(
    db: AsyncSession,
    model: Any,
    parent_clause: Any,
    group_id: uuid.UUID | None,
) -> None:
    """If ``group_id`` now has exactly one member, clear that member's
    ``superset_group_id`` — a superset of one is not a superset. No-op for
    ``None`` or for groups with 0 or 2+ members remaining."""
    if group_id is None:
        return
    remaining = (
        await db.execute(
            select(model.id).where(parent_clause, model.superset_group_id == group_id)
        )
    ).scalars().all()
    if len(remaining) == 1:
        await db.execute(
            update(model)
            .where(model.id == remaining[0])
            .values(superset_group_id=None)
        )
