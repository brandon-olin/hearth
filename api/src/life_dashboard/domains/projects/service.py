"""
Projects domain service.

A Project is a named container for todos and goals. Projects are household-scoped,
can nest up to 7 levels deep (via parent_id), and can optionally be pinned to the
sidebar nav (show_in_nav). System projects (is_system=True) cannot be deleted or
renamed — they serve as permanent inboxes (e.g. the default "To-dos" project).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.projects.models import Project, ProjectGoal
from life_dashboard.domains.projects.schemas import (
    ProjectCreate,
    ProjectGoalListResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)

MAX_DEPTH = 7


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_response(p: Project) -> ProjectResponse:
    return ProjectResponse(
        id=p.id,
        household_id=p.household_id,
        created_by_user_id=p.created_by_user_id,
        parent_id=p.parent_id,
        name=p.name,
        description=p.description,
        status=p.status,  # type: ignore[arg-type]
        due_date=p.due_date,
        is_system=p.is_system,
        show_in_nav=p.show_in_nav,
        sort_order=p.sort_order,
        archived_at=p.archived_at,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def _count_depth(
    db: AsyncSession,
    parent_id: uuid.UUID,
    household_id: uuid.UUID,
) -> int:
    """Count how many ancestors the given parent has (0 = root). Used to enforce MAX_DEPTH."""
    depth = 1  # the parent itself is at least depth 1
    current_id: uuid.UUID | None = parent_id
    while current_id is not None:
        result = await db.execute(
            select(Project.parent_id).where(
                Project.id == current_id,
                Project.household_id == household_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            break
        current_id = row[0]
        if current_id is not None:
            depth += 1
    return depth


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def list_projects(
    db: AsyncSession,
    household_id: uuid.UUID,
    parent_id: uuid.UUID | None = None,
    root_only: bool = False,
    show_in_nav: bool | None = None,
    include_archived: bool = False,
) -> ProjectListResponse:
    stmt = select(Project).where(Project.household_id == household_id)
    if root_only:
        stmt = stmt.where(Project.parent_id.is_(None))
    elif parent_id is not None:
        stmt = stmt.where(Project.parent_id == parent_id)
    if show_in_nav is not None:
        stmt = stmt.where(Project.show_in_nav == show_in_nav)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    stmt = stmt.order_by(Project.sort_order.asc(), Project.created_at.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return ProjectListResponse(items=[_to_response(p) for p in rows], total=len(rows))


async def get_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    household_id: uuid.UUID,
) -> ProjectResponse | None:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.household_id == household_id,
        )
    )
    p = result.scalar_one_or_none()
    return _to_response(p) if p else None


async def create_project(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ProjectCreate,
) -> tuple[ProjectResponse, None] | tuple[None, str]:
    """Returns (ProjectResponse, None) on success or (None, error_message) on failure."""
    if data.parent_id is not None:
        depth = await _count_depth(db, data.parent_id, household_id)
        if depth >= MAX_DEPTH:
            return None, f"Maximum project depth of {MAX_DEPTH} reached"

    p = Project(
        household_id=household_id,
        created_by_user_id=user_id,
        parent_id=data.parent_id,
        name=data.name,
        description=data.description,
        status=data.status,
        due_date=data.due_date,
        show_in_nav=data.show_in_nav,
        sort_order=data.sort_order,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _to_response(p), None


async def update_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    household_id: uuid.UUID,
    data: ProjectUpdate,
) -> tuple[ProjectResponse, None] | tuple[None, str]:
    """Returns (ProjectResponse, None) on success or (None, error_message) on failure."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.household_id == household_id,
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        return None, "not_found"

    updated = data.model_fields_set

    # System projects: only allow status, sort_order, show_in_nav updates
    if p.is_system:
        allowed = {"status", "sort_order", "show_in_nav"}
        for field in updated - allowed:
            updated.discard(field)

    if "name" in updated and data.name is not None:
        p.name = data.name
    if "description" in updated:
        p.description = data.description
    if "status" in updated and data.status is not None:
        p.status = data.status
    if "due_date" in updated:
        p.due_date = data.due_date
    if "parent_id" in updated:
        if data.parent_id is not None:
            depth = await _count_depth(db, data.parent_id, household_id)
            if depth >= MAX_DEPTH:
                return None, f"Maximum project depth of {MAX_DEPTH} reached"
        p.parent_id = data.parent_id
    if "show_in_nav" in updated and data.show_in_nav is not None:
        p.show_in_nav = data.show_in_nav
    if "sort_order" in updated and data.sort_order is not None:
        p.sort_order = data.sort_order

    p.updated_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(p)
    return _to_response(p), None


async def archive_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    household_id: uuid.UUID,
) -> tuple[ProjectResponse, None] | tuple[None, str]:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.household_id == household_id,
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        return None, "not_found"
    if p.is_system:
        return None, "system_protected"
    p.archived_at = datetime.now(tz=timezone.utc)
    p.status = "archived"
    p.updated_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(p)
    return _to_response(p), None


async def delete_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    household_id: uuid.UUID,
) -> tuple[bool, str | None]:
    """Returns (True, None) on success or (False, reason) on failure."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.household_id == household_id,
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        return False, "not_found"
    if p.is_system:
        return False, "system_protected"
    await db.delete(p)
    await db.commit()
    return True, None


# ── Goal relationships ────────────────────────────────────────────────────────

async def list_project_goals(
    db: AsyncSession,
    project_id: uuid.UUID,
    household_id: uuid.UUID,
) -> ProjectGoalListResponse | None:
    # Verify the project belongs to this household
    exists = (await db.execute(
        select(Project.id).where(
            Project.id == project_id,
            Project.household_id == household_id,
        )
    )).scalar_one_or_none()
    if not exists:
        return None

    rows = (await db.execute(
        select(ProjectGoal.goal_id).where(ProjectGoal.project_id == project_id)
    )).scalars().all()
    return ProjectGoalListResponse(items=list(rows), total=len(rows))


async def link_goal(
    db: AsyncSession,
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    """Link a goal to a project. Returns False if project not found, True otherwise (idempotent)."""
    exists = (await db.execute(
        select(Project.id).where(
            Project.id == project_id,
            Project.household_id == household_id,
        )
    )).scalar_one_or_none()
    if not exists:
        return False

    existing = (await db.execute(
        select(ProjectGoal).where(
            ProjectGoal.project_id == project_id,
            ProjectGoal.goal_id == goal_id,
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(ProjectGoal(project_id=project_id, goal_id=goal_id))
        await db.commit()
    return True


async def unlink_goal(
    db: AsyncSession,
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    """Unlink a goal from a project. Returns False if not found."""
    row = (await db.execute(
        select(ProjectGoal).where(
            ProjectGoal.project_id == project_id,
            ProjectGoal.goal_id == goal_id,
        )
    )).scalar_one_or_none()
    if not row:
        return False
    # Verify household ownership via project
    proj = (await db.execute(
        select(Project.id).where(
            Project.id == project_id,
            Project.household_id == household_id,
        )
    )).scalar_one_or_none()
    if not proj:
        return False
    await db.delete(row)
    await db.commit()
    return True


# ── Bootstrap seed ────────────────────────────────────────────────────────────

async def seed_system_project(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ProjectResponse:
    """
    Create the household's system "To-dos" project if it doesn't already exist.
    Called during household bootstrap and on upgrade for existing households.
    """
    existing = (await db.execute(
        select(Project).where(
            Project.household_id == household_id,
            Project.is_system.is_(True),
        )
    )).scalar_one_or_none()
    if existing:
        return _to_response(existing)

    p = Project(
        household_id=household_id,
        created_by_user_id=user_id,
        name="To-dos",
        status="active",
        is_system=True,
        show_in_nav=True,
        sort_order=0,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _to_response(p)
