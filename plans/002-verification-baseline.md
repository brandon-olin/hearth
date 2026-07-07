# Plan 002: Establish a verification baseline — test harness, first tests, and a CI gate

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- api/pyproject.toml api/src/life_dashboard/domains/todos/service.py api/src/life_dashboard/auth/hashing.py Makefile web/package.json`
> If any of these changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (purely additive — new test files, new scripts, new CI; no source behavior change)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

The repository has **zero automated tests** (`api/tests/` is an empty directory;
no `test_*.py` anywhere) even though the test harness is already configured in
`api/pyproject.toml` (pytest + pytest-asyncio, `asyncio_mode="auto"`,
`testpaths=["tests"]`). There is no one-command way to know the ~31,000 lines of
API code work, and the only CI (`.github/workflows/desktop.yml`) runs on release
tags, not on PRs. Every change — including the money-handling budget domain, auth,
and the household-scoping privacy invariant — ships unverified.

This plan creates the missing baseline: an installable, runnable test suite that
is **green on day one** (covering two real critical-path units — recurrence date
math and password hashing — that need no database), plus a reusable SQLite test
fixture that later plans build on, plus a CI workflow that runs lint + typecheck +
tests on every PR. It deliberately does **not** try to test everything — it makes
the harness exist and proves it works. Plans 003, 006, 008, 009, and 010 add
domain tests on top of the fixture this plan creates.

## Current state

- `api/tests/` — exists but is **empty** (no `__init__.py`, no `conftest.py`).
- `api/pyproject.toml` already declares the dev tooling and pytest config:
  ```toml
  [project.optional-dependencies]
  dev = [
      "pytest>=8.3.0",
      "pytest-asyncio>=0.24.0",
      "anyio[trio]>=4.7.0",
      "ruff>=0.8.0",
  ]

  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  testpaths = ["tests"]
  ```
  **However, the dev deps are NOT currently installed in `api/.venv`** (`import pytest`
  fails). Step 1 installs them.
- `api/.venv/` is the project virtualenv (contains `alembic`, `uvicorn`; pytest/ruff
  are missing until installed).
- The function under test for recurrence: `todos/service.py:23`
  ```python
  def _next_due_date(base: date, rule: dict) -> date:
  ```
  `base` is a `datetime.date`; `rule` is a dict shaped like
  `{"frequency": "daily"|"weekdays"|"weekly"|"monthly_date"|"monthly_weekday"|"yearly",
    "interval": int, "days_of_week": list[int], "end_date": str|None}`. It is a pure
  function (no DB, no I/O). `api/CLAUDE.md` documents its edge cases: "May 31 → June 30,
  Feb 29 → Mar 1, biweekly weekday snap."
- Password hashing: `auth/hashing.py` exposes pure functions:
  ```python
  def hash_password(plain: str) -> str: ...
  def verify_password(plain: str, hashed: str) -> bool: ...
  ```
  (argon2-based; no DB).
- DB plumbing (for the fixture): `core/database.py` defines `class Base(DeclarativeBase)`
  (line 62), an async `get_db()` dependency (line 66), and `create_all_tables()`. Models
  use **generic** SQLAlchemy column types (`Uuid()`, `JSON`, `Numeric`, `Date`,
  `DateTime`) — not Postgres-only dialect types — so `Base.metadata.create_all` works on
  SQLite for the core domain tables. Importing `life_dashboard.main` registers every
  model (all routers/models are imported there).
- Verification commands do not exist yet: `Makefile` has no `test`/`lint` target;
  `web/package.json` scripts are `dev`/`build`/`start`/`lint`/`codegen` — no `typecheck`.

Convention to match: pytest async tests. Because `asyncio_mode="auto"` is set, an
`async def test_*` function is automatically treated as an async test — you do NOT
need an `@pytest.mark.asyncio` decorator.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install dev deps | `cd api && .venv/bin/pip install -e ".[dev]"` | exit 0; pytest + ruff installed |
| Run API tests | `cd api && .venv/bin/python -m pytest` | all pass |
| Run API tests (verbose) | `cd api && .venv/bin/python -m pytest -v` | lists each test PASSED |
| Lint API | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |
| Web typecheck | `cd web && npx tsc --noEmit` | exit 0 (or pre-existing errors unrelated to this plan — see STOP) |
| Web lint | `cd web && npm run lint` | exit 0 |

## Scope

**In scope** (create unless noted):
- `api/tests/__init__.py` (create, empty)
- `api/tests/conftest.py` (create)
- `api/tests/test_recurrence.py` (create)
- `api/tests/test_password_hashing.py` (create)
- `api/tests/test_schema_smoke.py` (create)
- `Makefile` (edit — add `test`, `lint`, `check` targets)
- `web/package.json` (edit — add `typecheck` script)
- `.github/workflows/ci.yml` (create)

**Out of scope** (do NOT touch):
- Any file under `api/src/` — this plan does not change application code.
- The existing `.github/workflows/desktop.yml` — leave it exactly as is.
- Adding domain/service tests beyond the schema smoke test — that is the job of
  plans 003/006/008/009/010, which reuse the fixture from here.

## Git workflow

- Branch: `advisor/002-verification-baseline`
- Commit style: conventional commits, e.g. `test(api): add pytest baseline, fixtures, and CI gate`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Install the dev dependencies

```
cd api && .venv/bin/pip install -e ".[dev]"
```

**Verify**: `cd api && .venv/bin/python -c "import pytest, ruff; print('ok')"` → prints `ok`.

### Step 2: Create the test package and pure-unit recurrence tests (no DB)

Create `api/tests/__init__.py` (empty file).

Create `api/tests/test_recurrence.py`. First read `todos/service.py:23` and the
`_next_due_date` body to confirm the exact rule keys and behavior, then write tests
asserting the documented edge cases. Target shape:

```python
from datetime import date

from life_dashboard.domains.todos.service import _next_due_date


def test_daily_advances_one_day():
    assert _next_due_date(date(2026, 1, 1), {"frequency": "daily", "interval": 1}) == date(2026, 1, 2)


def test_weekly_interval_two_weeks():
    # biweekly from a Thursday lands two weeks later
    result = _next_due_date(date(2026, 1, 1), {"frequency": "weekly", "interval": 2, "days_of_week": [3]})
    assert (result - date(2026, 1, 1)).days % 7 == 0


def test_monthly_date_clamps_may31_to_june30():
    # May 31 + 1 month has no June 31 → clamp to June 30
    assert _next_due_date(date(2026, 5, 31), {"frequency": "monthly_date", "interval": 1}) == date(2026, 6, 30)


def test_yearly_leap_day_feb29_to_mar1():
    # Feb 29 (leap) + 1 year has no Feb 29 in 2027 → the documented Mar 1 fallback
    assert _next_due_date(date(2024, 2, 29), {"frequency": "yearly", "interval": 1}) == date(2025, 3, 1)
```

**IMPORTANT**: If reading the actual `_next_due_date` implementation shows a
different result for any of these inputs than asserted above, this is a
**characterization** suite — change the *assertion to match the real current
behavior* and add a `# characterizes current behavior` comment. Do NOT change the
source function. The goal is to pin what the code does today.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_recurrence.py -v` → all pass.

### Step 3: Create password-hashing tests (no DB)

Create `api/tests/test_password_hashing.py`:

```python
from life_dashboard.auth.hashing import hash_password, verify_password


def test_hash_is_not_plaintext():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert len(h) > 20


def test_verify_accepts_correct_password():
    h = hash_password("s3cret-pw")
    assert verify_password("s3cret-pw", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("s3cret-pw")
    assert verify_password("wrong-pw", h) is False


def test_two_hashes_of_same_password_differ():
    # argon2 salts each hash — two hashes of the same input must not be equal
    assert hash_password("abc") != hash_password("abc")
```

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_password_hashing.py -v` → all pass.

### Step 4: Create the reusable SQLite DB fixture (`conftest.py`) + a schema smoke test

Create `api/tests/conftest.py`. This fixture provides an in-memory SQLite database
shared across one test (via `StaticPool`) and a clean `AsyncSession` per test. Later
plans depend on the `db_session` fixture defined here.

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing main registers every ORM model on Base.metadata (all routers/models
# are imported there), so create_all builds the full schema.
import life_dashboard.main  # noqa: F401
from life_dashboard.core.database import Base


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session

    await engine.dispose()
```

Create `api/tests/test_schema_smoke.py` — proves the fixture and schema work on
SQLite without asserting on any Postgres-only feature:

```python
from sqlalchemy import inspect


async def test_core_tables_are_created(db_session):
    def _tables(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    conn = await db_session.connection()
    names = await conn.run_sync(_tables)

    # A representative slice of the domains later plans will test against.
    for expected in ("households", "users", "todos", "goals", "budget_categories", "budget_profiles"):
        assert expected in names, f"table {expected!r} missing from SQLite schema"
```

If you are unsure of a table name, inspect it: the table name is the SQLAlchemy
`__tablename__` on each model (e.g. `budget/models.py` `class BudgetCategory` →
check its `__tablename__`). Adjust the expected names in the test to match the real
`__tablename__` values rather than guessing.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_schema_smoke.py -v` → passes.

If `Base.metadata.create_all` raises on SQLite because some model uses a
Postgres-only construct, see STOP conditions — do not try to rewrite models.

### Step 5: Add `make` targets and a web `typecheck` script

In `Makefile`, add these targets (match the existing tab-indented recipe style;
note the existing targets call tools via `api/.venv/bin/...`):

```makefile
test:
	cd api && .venv/bin/python -m pytest

lint:
	cd api && .venv/bin/python -m ruff check src tests
	cd web && npm run lint

check: lint test
	cd web && npx tsc --noEmit
```

Also add `test`, `lint`, `check` to the `.PHONY` line at the top of the `Makefile`.

In `web/package.json`, add a `typecheck` script to the `scripts` block:

```json
"typecheck": "tsc --noEmit",
```

**Verify**:
- `cd api && .venv/bin/python -m pytest` → all pass (all four test files).
- `cd api && .venv/bin/python -m ruff check src tests` → exit 0 (if ruff flags
  pre-existing issues in `src`, see STOP — do not fix `src` here; you may narrow the
  lint target to `tests` only and note it in your report).
- `cd web && npx tsc --noEmit` → record the result. If it reports pre-existing
  errors unrelated to this plan, do NOT fix them here — note them and continue
  (see STOP).

### Step 6: Add the PR CI workflow

Create `.github/workflows/ci.yml`. It must not collide with the existing
`desktop.yml`. Use this content:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  api:
    name: API — lint & tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        working-directory: api
        run: |
          python -m venv .venv
          .venv/bin/pip install -e ".[dev]"
      - name: Ruff
        working-directory: api
        run: .venv/bin/python -m ruff check src tests
      - name: Pytest
        working-directory: api
        run: .venv/bin/python -m pytest

  web:
    name: Web — lint & typecheck
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Install
        working-directory: web
        run: npm ci
      - name: Lint
        working-directory: web
        run: npm run lint
      - name: Typecheck
        working-directory: web
        run: npx tsc --noEmit
```

If the `ruff check src` step is known to fail on pre-existing `src` issues (from
Step 5), change the CI Ruff line to `.venv/bin/python -m ruff check tests` and note
this narrowing in your completion report so the operator can schedule a `src`
lint-cleanup follow-up.

**Verify**: the file is valid YAML — `cd . && python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"` → no error. (If `pyyaml` isn't available, visually confirm indentation matches the block above.)

## Test plan

- New test files: `test_recurrence.py` (4 cases), `test_password_hashing.py` (4 cases),
  `test_schema_smoke.py` (1 case). Total ≥ 9 tests, all passing.
- These are the pattern later plans copy: pure-unit tests need no fixture; DB tests
  take the `db_session` fixture from `conftest.py`.
- Verification: `cd api && .venv/bin/python -m pytest -v` → ≥ 9 passed, 0 failed.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `cd api && .venv/bin/python -c "import pytest, ruff; print('ok')"` → `ok`
- [ ] `cd api && .venv/bin/python -m pytest` → ≥ 9 passed, 0 failed
- [ ] `cd api && .venv/bin/python -m ruff check tests` → exit 0
- [ ] `cd web && npx tsc --noEmit` → exit 0, OR pre-existing unrelated errors documented in the report
- [ ] `make test` runs the suite; `make check` exists
- [ ] `web/package.json` has a `typecheck` script
- [ ] `.github/workflows/ci.yml` exists and is valid YAML
- [ ] No files under `api/src/` modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `Base.metadata.create_all` fails on SQLite because a model uses a Postgres-only
  type/construct (e.g. `TSVECTOR`, a dialect-specific default). Report which table.
  The fallback is a Postgres-backed test DB, which is a larger design decision for
  the operator — do NOT rewrite model column types to work around it.
- `.venv/bin/pip install -e ".[dev]"` fails (e.g. no network, Python < 3.12). Report
  the error; the whole plan is blocked on it.
- `npx tsc --noEmit` reports a large number of pre-existing errors — note the count
  and a few examples, keep the CI `web` job (it documents the debt), and do NOT
  attempt to fix `src/` type errors in this plan.
- A test you wrote fails because the real code behaves differently than the example
  assertions — for `test_recurrence.py` this is expected (characterize the real
  behavior, per Step 2); for the others, report the discrepancy.

## Maintenance notes

- The `db_session` fixture is the shared entry point for all future service-layer
  tests. Plans 003, 006, 008, 009, 010 import it. If its signature changes, those
  plans' tests must be updated in lockstep.
- SQLite is a *test-only* convenience here; production runs Postgres. Any test that
  depends on a Postgres-specific behavior (full-text search via TSVECTOR, JSONB
  path operators) must be marked and skipped on SQLite, or moved to a Postgres CI
  job later. Keep this in mind when reviewing PRs that add tests touching search.
- Reviewer should confirm the CI workflow triggers on PRs and that `make check` is
  the single command a contributor runs before pushing.
- Follow-up deferred: a `ruff check src` cleanup pass if Step 5 revealed pre-existing
  lint debt; a Postgres CI matrix job once tests need Postgres-only features.
