import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.visibility import apply_visibility_filter
from life_dashboard.domains.todos.models import Todo
from life_dashboard.domains.todos.schemas import (
    TodoCreate,
    TodoListResponse,
    TodoResponse,
    TodoUpdate,
)
from life_dashboard.domains.notifications import service as notifications


def _to_response(todo: Todo) -> TodoResponse:
    return TodoResponse.model_validate(todo)


def _next_due_date(base: date, rule: dict) -> date:
    """Return the next due date for a recurring todo after *base*."""
    frequency = rule.get("frequency", "weekly")
    interval = max(1, int(rule.get("interval", 1)))

    if frequency == "daily":
        return base + timedelta(days=interval)

    if frequency == "weekdays":
        candidate = base + timedelta(days=1)
        while candidate.weekday() >= 5:  # skip Sat (5) and Sun (6)
            candidate += timedelta(days=1)
        return candidate

    if frequency == "weekly":
        days: list[int] = rule.get("days_of_week") or [base.weekday()]
        if interval == 1:
            # Walk forward day-by-day and return the first matching weekday
            candidate = base + timedelta(days=1)
            for _ in range(7):
                if candidate.weekday() in days:
                    return candidate
                candidate += timedelta(days=1)
        # interval > 1: advance N full weeks then snap to nearest selected day
        target = base + timedelta(weeks=interval)
        for i in range(7):
            if target.weekday() in days:
                return target
            target += timedelta(days=1)
        return base + timedelta(weeks=interval)

    if frequency == "monthly_date":
        month = base.month - 1 + interval
        year = base.year + month // 12
        month = month % 12 + 1
        day = min(base.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    if frequency == "monthly_weekday":
        # Preserve both the week-of-month index and the weekday.
        # Example: "2nd Tuesday" → week_num=1 (0-indexed), weekday=1
        week_num = (base.day - 1) // 7
        weekday = base.weekday()
        month = base.month - 1 + interval
        year = base.year + month // 12
        month = month % 12 + 1
        first = date(year, month, 1)
        days_ahead = (weekday - first.weekday()) % 7
        candidate = first + timedelta(days=days_ahead + week_num * 7)
        # If it overflowed into the next month, step back one week
        if candidate.month != month:
            candidate -= timedelta(weeks=1)
        return candidate

    if frequency == "yearly":
        try:
            return base.replace(year=base.year + interval)
        except ValueError:
            # Feb 29 in a non-leap target year → March 1
            return date(base.year + interval, 3, 1)

    # Fallback
    return base + timedelta(weeks=interval)


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
        visibility=data.visibility,
        shared_with_user_ids=data.shared_with_user_ids or [],
    )
    db.add(todo)
    await db.flush()  # get todo.id before committing

    # Notify the assignee when a todo is created already assigned to someone.
    if todo.assigned_to_user_id is not None:
        await notifications.dispatch(
            db,
            household_id=household_id,
            recipient_id=todo.assigned_to_user_id,
            actor_id=user_id,
            type="todo_assigned",
            entity_type="todo",
            entity_id=todo.id,
            payload={"title": todo.title},
        )

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
    user_id: uuid.UUID,
    *,
    status: str | None = None,
    project_id: uuid.UUID | None = None,
    due_date_from: date | None = None,
    due_date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> TodoListResponse:
    query = select(Todo).where(Todo.household_id == household_id)
    query = apply_visibility_filter(query, Todo, user_id)
    if status is not None:
        query = query.where(Todo.status == status)
    if project_id is not None:
        query = query.where(Todo.project_id == project_id)
    if due_date_from is not None:
        query = query.where(Todo.due_date >= due_date_from)
    if due_date_to is not None:
        query = query.where(Todo.due_date <= due_date_to)

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
    actor_id: uuid.UUID | None = None,
) -> TodoResponse | None:
    result = await db.execute(
        select(Todo).where(Todo.id == todo_id, Todo.household_id == household_id)
    )
    todo = result.scalar_one_or_none()
    if todo is None:
        return None

    # Capture the previous assignee before we apply the update.
    prev_assignee = todo.assigned_to_user_id

    for field in data.model_fields_set:
        setattr(todo, field, getattr(data, field))

    # Auto-stamp completed_at when status transitions to/from done
    if "status" in data.model_fields_set and "completed_at" not in data.model_fields_set:
        if data.status == "done":
            todo.completed_at = datetime.now(tz=timezone.utc)
        else:
            todo.completed_at = None

    todo.updated_at = datetime.now(tz=timezone.utc)

    # Auto-spawn the next instance when a recurring todo is completed.
    # The completed todo is preserved as history; a fresh pending copy is created.
    next_todo: Todo | None = None
    if (
        "status" in data.model_fields_set
        and data.status == "done"
        and todo.recurring
    ):
        rule = todo.recurring
        base = todo.due_date or date.today()
        next_due = _next_due_date(base, rule)

        end_date_str: str | None = rule.get("end_date")
        end_date = date.fromisoformat(end_date_str) if end_date_str else None

        if end_date is None or next_due <= end_date:
            next_todo = Todo(
                household_id=todo.household_id,
                created_by_user_id=todo.created_by_user_id,
                project_id=todo.project_id,
                assigned_to_user_id=todo.assigned_to_user_id,
                title=todo.title,
                description=todo.description,
                status="pending",
                priority=todo.priority,
                due_date=next_due,
                recurring=todo.recurring,
                visibility=todo.visibility,
                shared_with_user_ids=todo.shared_with_user_ids,
            )
            db.add(next_todo)

    # Notify the new assignee if assignment changed (and someone is now assigned).
    if (
        "assigned_to_user_id" in data.model_fields_set
        and todo.assigned_to_user_id is not None
        and todo.assigned_to_user_id != prev_assignee
    ):
        await notifications.dispatch(
            db,
            household_id=household_id,
            recipient_id=todo.assigned_to_user_id,
            actor_id=actor_id,
            type="todo_assigned",
            entity_type="todo",
            entity_id=todo.id,
            payload={"title": todo.title},
        )

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
