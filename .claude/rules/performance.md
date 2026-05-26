---
description: Performance rules for the FastAPI/SQLAlchemy backend. Prevents the most common production performance issues.
paths:
  - "api/src/life_dashboard/**"
---

# Performance Rules

## N+1 queries — the most common issue in this codebase

Never query inside a loop or `.map()` equivalent. If you need related data for a list of entities, batch-load it in one query and group in Python.

The habit list endpoint is the canonical example of the correct pattern:
```python
# Batch-load all occurrences for all returned habits in a single query
occ_result = await db.execute(
    select(HabitOccurrence.habit_id, HabitOccurrence.scheduled_date)
    .where(HabitOccurrence.habit_id.in_(habit_ids), ...)
)
occs_by_habit: dict[uuid.UUID, set[date]] = {}
for habit_id, sched_date in occ_result.all():
    occs_by_habit.setdefault(habit_id, set()).add(sched_date)
```

Before writing any query inside a loop, stop and write a batch query instead.

verify: Grep("for .* in .*:\s*\n.*await db", path="api/src/life_dashboard/domains/", multiline=true) → 0 matches (manual review)

## Missing indexes

Every new query pattern needs an index. When you add a `WHERE` clause on a column that isn't the primary key, check whether an index exists. If not, add it in the same migration.

Common cases in this codebase:
- Filtering by `household_id` — all domain tables should have this indexed (compound indexes with the primary filter field are best)
- Filtering by `status`, `archived_at`, `due_date` — add when those become query params

## Unbounded queries

All list endpoints must have a `LIMIT`. Never `SELECT *` all rows and filter in Python:

```python
# WRONG — loads entire table
all_todos = await db.scalars(select(Todo).where(Todo.household_id == hid))
pending = [t for t in all_todos if t.status == "pending"]

# CORRECT — filtered and limited at the DB
pending = await db.scalars(
    select(Todo)
    .where(Todo.household_id == hid, Todo.status == "pending")
    .limit(100)
)
```

For streak and completion rate calculations, the lookback is capped: 90 days for list endpoints, 365 days for specific habit detail. Enforce these caps — do not remove them.

## JSONB performance

JSONB columns (`habits.cadence`, `todos.recurring`, `documents.editor_json`, `recipes.ingredients`) cannot be efficiently indexed for arbitrary sub-field queries. If a query needs to filter by a JSONB sub-field frequently, that sub-field should be promoted to a real column with a migration.

Do not `SELECT` large JSONB columns (e.g. `documents.editor_json`) in list endpoints — select only the fields needed for the list view.

## Async correctness

All database calls must be `await`ed. Using synchronous SQLAlchemy calls in an async context will block the event loop.

Use `Promise.all()` equivalent patterns (concurrent `asyncio.gather`) for independent async operations rather than sequential `await` chains.
