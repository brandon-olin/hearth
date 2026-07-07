"""Regression test for recurring-todo completion idempotency (plan 007).

Re-PATCHing an already-`done` recurring todo with status="done" (a mobile
double-tap, a retried request, a background refetch that re-submits) must NOT
spawn another next instance. The prior-status gate in `update_todo` is what
enforces this; this test fails against the pre-fix code.

The concurrency case (two simultaneous completers) is guarded by the
`with_for_update()` row lock, which SQLite ignores — so it is verified by code
review, not by this test.
"""

from datetime import date

from sqlalchemy import select

from life_dashboard.auth.models import Household
from life_dashboard.domains.todos import service as todos_service
from life_dashboard.domains.todos.models import Todo
from life_dashboard.domains.todos.schemas import TodoUpdate


async def _seed(db, rule):
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    todo = Todo(
        household_id=hh.id,
        title="T",
        status="pending",
        due_date=date(2026, 1, 1),
        recurring=rule,
    )
    db.add(todo)
    await db.flush()
    return hh, todo


async def test_recompleting_done_recurring_todo_does_not_spawn_again(db_session):
    hh, todo = await _seed(db_session, {"frequency": "daily", "interval": 1})

    # First completion → spawns exactly one next instance (total 2).
    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))
    # Second identical completion (double-tap / retry) → must NOT spawn a third.
    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))

    rows = await db_session.execute(select(Todo).where(Todo.household_id == hh.id))
    todos = list(rows.scalars().all())
    assert len(todos) == 2  # completed original + exactly one pending — NOT 3
