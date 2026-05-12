import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.todos.models import Todo
from life_dashboard.domains.todos.schemas import (
    TodoCreate,
    TodoListResponse,
    TodoResponse,
    TodoUpdate,
)


def _to_response(todo: Todo) -> TodoResponse:
    return TodoResponse.model_validate(todo)


async def create_todo(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: TodoCreate,
) -> TodoResponse:
    todo = Todo(
        household_id=household_id,
        created_by_user_id=user_id,
        project_id=data.project_id,
        assigned_to_user_id=data.assigned_to_user_id,
        title=data.title,
        description=data.description,
        status=data.status,
        priority=data.priority,
        due_date=data.due_date,
        recurring=data.recurring,
    )
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return _to_response(todo)


async def get_todo(
    db: AsyncSession,
    todo_id: uuid.UUID,
    household_id: uuid.UUID,
) -> TodoResponse | None:
    result = await db.execute(
        select(Todo).where(Todo.id == todo_id, Todo.household_id == household_id)
    )
    todo = result.scalar_one_or_none()
    return _to_response(todo) if todo else None


async def list_todos(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    status: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> TodoListResponse:
    query = select(Todo).where(Todo.household_id == household_id)
    if status is not None:
        query = query.where(Todo.status == status)
    if project_id is not None:
        query = query.where(Todo.project_id == project_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    todos = list(
        (await db.execute(
            query.order_by(Todo.due_date.asc().nulls_last(), Todo.created_at.desc())
            .limit(limit).offset(offset)
        )).scalars().all()
    )
    return TodoListResponse(
        items=[_to_response(t) for t in todos],
        total=total, limit=limit, offset=offset,
    )


async def update_todo(
    db: AsyncSession,
    todo_id: uuid.UUID,
    household_id: uuid.UUID,
    data: TodoUpdate,
) -> TodoResponse | None:
    result = await db.execute(
        select(Todo).where(Todo.id == todo_id, Todo.household_id == household_id)
    )
    todo = result.scalar_one_or_none()
    if todo is None:
        return None

    for field in data.model_fields_set:
        setattr(todo, field, getattr(data, field))

    # Auto-stamp completed_at when status transitions to/from done
    if "status" in data.model_fields_set and "completed_at" not in data.model_fields_set:
        if data.status == "done":
            todo.completed_at = datetime.now(tz=timezone.utc)
        else:
            todo.completed_at = None

    todo.updated_at = datetime.now(tz=timezone.utc)

    await db.commit()
    await db.refresh(todo)
    return _to_response(todo)


async def delete_todo(
    db: AsyncSession,
    todo_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Todo).where(Todo.id == todo_id, Todo.household_id == household_id)
    )
    todo = result.scalar_one_or_none()
    if todo is None:
        return False
    await db.delete(todo)
    await db.commit()
    return True
