import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.core.permissions import (
    check_permission,
    get_item_creator,
    load_household_permissions,
)
from life_dashboard.domains.projects.models import Project
from life_dashboard.domains.projects import service
from life_dashboard.domains.projects.schemas import (
    ProjectCreate,
    ProjectGoalListResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    parent_id: uuid.UUID | None = Query(None),
    root_only: bool = Query(False),
    show_in_nav: bool | None = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.list_projects(
        db,
        household_id=current_user.household_id,
        user_id=current_user.id,
        parent_id=parent_id,
        root_only=root_only,
        show_in_nav=show_in_nav,
        include_archived=include_archived,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    perms = await load_household_permissions(db, current_user.household_id)
    if not check_permission(perms, "projects", "create", current_user.role):
        raise HTTPException(status_code=403, detail="You don't have permission to create projects.")
    project, error = await service.create_project(
        db,
        household_id=current_user.household_id,
        user_id=current_user.id,
        data=data,
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await service.get_project(
        db, project_id=project_id, household_id=current_user.household_id, user_id=current_user.id
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    creator_id = await get_item_creator(db, Project, project_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "projects", "manage_others", current_user.role):
            raise HTTPException(
                status_code=403, detail="You don't have permission to edit others' projects."
            )
    project, error = await service.update_project(
        db,
        project_id=project_id,
        household_id=current_user.household_id,
        data=data,
    )
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Project not found")
    if error:
        raise HTTPException(status_code=400, detail=error)
    return project


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    creator_id = await get_item_creator(db, Project, project_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "projects", "manage_others", current_user.role):
            raise HTTPException(
                status_code=403, detail="You don't have permission to archive others' projects."
            )
    project, error = await service.archive_project(
        db, project_id=project_id, household_id=current_user.household_id
    )
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Project not found")
    if error == "system_protected":
        raise HTTPException(status_code=403, detail="System projects cannot be archived")
    if error:
        raise HTTPException(status_code=400, detail=error)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    creator_id = await get_item_creator(db, Project, project_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "projects", "manage_others", current_user.role):
            raise HTTPException(
                status_code=403, detail="You don't have permission to delete others' projects."
            )
    deleted, error = await service.delete_project(
        db, project_id=project_id, household_id=current_user.household_id
    )
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Project not found")
    if error == "system_protected":
        raise HTTPException(status_code=403, detail="System projects cannot be deleted")
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")


# ── Goal relationships ────────────────────────────────────────────────────────

@router.get("/{project_id}/goals", response_model=ProjectGoalListResponse)
async def list_project_goals(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await service.list_project_goals(
        db, project_id=project_id, household_id=current_user.household_id, user_id=current_user.id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.put("/{project_id}/goals/{goal_id}", status_code=204)
async def link_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Link a goal to a project (idempotent)."""
    ok = await service.link_goal(
        db,
        project_id=project_id,
        goal_id=goal_id,
        household_id=current_user.household_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")


@router.delete("/{project_id}/goals/{goal_id}", status_code=204)
async def unlink_goal(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unlink a goal from a project."""
    ok = await service.unlink_goal(
        db,
        project_id=project_id,
        goal_id=goal_id,
        household_id=current_user.household_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Project-goal link not found")
