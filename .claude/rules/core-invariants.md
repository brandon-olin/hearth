---
description: Critical invariants that must survive context compression. Rules that caused or would cause real bugs if violated. Load on every file.
paths:
  - "**/*"
---

# Core Invariants

These load on every file edit. They exist because violating them causes data leakage, silent corruption, or broken idempotency.

## 1. Household scoping — data isolation boundary

Every database query in a service function must filter by `household_id`. No exceptions.

A query that returns records without scoping to the current user's household leaks data across households — this is a design bug, not a style issue.

```python
# WRONG — leaks across households
todos = await db.execute(select(Todo).where(Todo.id == todo_id))

# CORRECT — scoped
todos = await db.execute(
    select(Todo).where(Todo.id == todo_id, Todo.household_id == current_user.household_id)
)
```

verify: Grep("select\(.*\)\.where\((?!.*household_id)", path="api/src/life_dashboard/domains/") → manual check: review any new queries added in service.py files

## 2. Writes through service layer only

Routers call service functions. Service functions call the database. Routers never touch `db` directly.

```python
# WRONG — ad-hoc DB access from router
@router.post("/todos")
async def create_todo(data: TodoCreate, db: AsyncSession = Depends(get_db)):
    todo = Todo(**data.dict())
    db.add(todo)  # ← never do this in a router
    await db.commit()

# CORRECT — router delegates to service
@router.post("/todos")
async def create_todo(data: TodoCreate, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    return await todos_service.create_todo(db, user.household_id, data)
```

verify: Grep("db\.add\(|db\.execute\(|db\.commit\(", path="api/src/life_dashboard/domains/*/router.py") → 0 matches

## 3. Idempotency on state-transition operations

State transitions that trigger side-effects (creating the next recurrence instance) must be atomic. The check and the create happen inside a single transaction, using `SELECT FOR UPDATE` or `UPDATE … WHERE … RETURNING`.

Never check existence in one query and insert in a separate query without a lock — the gap is a race window.

```python
# WRONG — race window between check and create
todo = await db.get(Todo, todo_id)
if todo.completed_at is None:
    todo.completed_at = datetime.now(timezone.utc)
    _create_next_instance(db, todo)  # concurrent request may also reach here

# CORRECT — atomic with FOR UPDATE
async with db.begin():
    row = await db.execute(select(Todo).where(Todo.id == todo_id).with_for_update())
    todo = row.scalar_one_or_none()
    if todo and todo.completed_at is None:
        todo.completed_at = datetime.now(timezone.utc)
        _create_next_instance(db, todo)
```

verify: manual — check any new PATCH endpoint that marks a recurring entity complete

## 4. No hardcoded colors in frontend JSX/TSX

All colors must come from CSS variables or Tailwind semantic classes. Hardcoded color values (`bg-blue-100`, `text-amber-700`, `#3b82f6`, `oklch(...)`) break theme switching.

```tsx
// WRONG
<span className="bg-blue-100 text-blue-800">Active</span>

// CORRECT — semantic Tailwind or badge system
<span className="badge badge-primary">Active</span>
<span className="bg-primary text-primary-foreground">Active</span>
```

verify: Grep("className=.*bg-(red|blue|green|amber|violet|indigo|pink|orange|yellow|teal|cyan|purple|rose|lime|sky|fuchsia|slate|zinc|neutral|stone|gray|emerald)-", path="web/src/") → 0 matches

## 5. `$api` for all data fetching; `resolveMediaUrl` for upload URLs

All API calls go through `$api` from `src/lib/api/query.ts`. Raw `fetch()` calls must use `apiBaseUrl` from `client.ts` — never hardcode `/api/`. Upload URLs in `<img src>` must go through `resolveMediaUrl()` for Tauri compatibility.

```typescript
// WRONG
const res = await fetch("/api/recipes");
<img src={recipe.cover_image_url} />

// CORRECT
const { data } = $api.useQuery("get", "/recipes");
import { resolveMediaUrl } from "@/lib/api/client";
<img src={resolveMediaUrl(recipe.cover_image_url) ?? ""} />
```

verify: Grep("fetch\(['\`]/api/", path="web/src/") → 0 matches
