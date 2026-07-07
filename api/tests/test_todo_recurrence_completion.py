"""Characterization tests for recurring-todo completion → next-instance spawn.

These pin the *correct* behaviors of `update_todo` that plan 007's atomicity
refactor must not regress: completing a recurring todo spawns exactly one next
instance with the right due date and copied fields, and nothing spawns once the
recurrence `end_date` has passed.

The idempotent-re-completion (double-submit) regression test is intentionally
deferred to plan 007 — the current code has no prior-status gate, and that is
the bug 007 fixes, not a behavior characterized here.
"""

from datetime import date

from sqlalchemy import select

from life_dashboard.auth.models import Household
from life_dashboard.domains.todos import service as todos_service
from life_dashboard.domains.todos.models import Todo
from life_dashboard.domains.todos.schemas import TodoUpdate


async def _seed_recurring_todo(db, *, rule, due=date(2026, 1, 1)):
    hh = Household(name="H")
    db.add(hh)
    await db.flush()
    todo = Todo(
        household_id=hh.id,
        title="Water plants",
        status="pending",
        due_date=due,
        recurring=rule,
    )
    db.add(todo)
    await db.flush()
    return hh, todo


async def _all_todos(db, household_id):
    rows = await db.execute(select(Todo).where(Todo.household_id == household_id))
    return list(rows.scalars().all())


async def test_completing_recurring_todo_spawns_exactly_one_next_instance(db_session):
    hh, todo = await _seed_recurring_todo(
        db_session, rule={"frequency": "daily", "interval": 1}, due=date(2026, 1, 1)
    )

    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))

    todos = await _all_todos(db_session, hh.id)
    assert len(todos) == 2  # the completed one + exactly one new pending instance
    pending = [t for t in todos if t.status == "pending"]
    assert len(pending) == 1
    assert pending[0].due_date == date(2026, 1, 2)  # daily → next day


async def test_no_next_instance_created_past_end_date(db_session):
    hh, todo = await _seed_recurring_todo(
        db_session,
        rule={"frequency": "daily", "interval": 1, "end_date": "2026-01-01"},
        due=date(2026, 1, 1),
    )

    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))

    todos = await _all_todos(db_session, hh.id)
    assert len(todos) == 1  # next due (Jan 2) is past end_date (Jan 1) → no spawn
    assert todos[0].status == "done"


async def test_spawned_instance_copies_recurring_rule_and_title(db_session):
    rule = {"frequency": "weekly", "interval": 1, "days_of_week": [3]}
    hh, todo = await _seed_recurring_todo(db_session, rule=rule, due=date(2026, 1, 1))

    await todos_service.update_todo(db_session, todo.id, hh.id, TodoUpdate(status="done"))

    todos = await _all_todos(db_session, hh.id)
    pending = [t for t in todos if t.status == "pending"]
    assert len(pending) == 1
    assert pending[0].title == "Water plants"
    assert pending[0].recurring == rule
