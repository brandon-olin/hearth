import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.core.permissions import (
    check_permission,
    get_item_creator,
    load_household_permissions,
)
from life_dashboard.domains.todos.models import Todo
from life_dashboard.domains.todos.schemas import (
    TodoCreate,
    TodoListResponse,
    TodoResponse,
    TodoUpdate,
)
from life_dashboard.domains.todos import service

router = APIRouter(prefix="/todos", tags=["todos"])


@router.get("", response_model=TodoListResponse)
async def list_todos(
    status: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    due_date_from: date | None = Query(default=None),
    due_date_to: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TodoListResponse:
    return await service.list_todos(
        db, current_user.household_id, current_user.id,
        status=status, project_id=project_id,
        due_date_from=due_date_from, due_date_to=due_date_to,
        limit=limit, offset=offset,
    )


@router.get("/{todo_id}", response_model=TodoResponse)
async def get_todo(
    todo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TodoResponse:
    todo = await service.get_todo(db, todo_id, current_user.household_id)
    if todo is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return todo


@router.post("", response_model=TodoResponse, status_code=http_status.HTTP_201_CREATED)
async def create_todo(
    data: TodoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TodoResponse:
    perms = await load_household_permissions(db, current_user.household_id)
    if not check_permission(perms, "todos", "create", current_user.role):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to create to-dos.",
        )
    return await service.create_todo(db, current_user.household_id, current_user.id, data)


@router.patch("/{todo_id}", response_model=TodoResponse)
async def update_todo(
    todo_id: uuid.UUID,
    data: TodoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TodoResponse:
    creator_id = await get_item_creator(db, Todo, todo_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Todo not found")
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "todos", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit others' to-dos.",
            )
    todo = await service.update_todo(db, todo_id, current_user.household_id, data, actor_id=current_user.id)
    if todo is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return todo


@router.delete("/{todo_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_todo(
    todo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    creator_id = await get_item_creator(db, Todo, todo_id, current_user.household_id)
    if creator_id is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Todo not found")
    if creator_id != current_user.id:
        perms = await load_household_permissions(db, current_user.household_id)
        if not check_permission(perms, "todos", "manage_others", current_user.role):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete others' to-dos.",
            )
    deleted = await service.delete_todo(db, todo_id, current_user.household_id)
    if not deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Todo not found")
