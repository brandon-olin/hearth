# Plan 005: Stop leaking internal exception details to API clients

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- api/src/life_dashboard/main.py`
> If `main.py` changed since this plan was written, compare the "Current state"
> excerpt against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (narrows a response body; the full traceback is already logged server-side)
- **Depends on**: plans/002-verification-baseline.md (for the test)
- **Category**: security
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

The catch-all exception handler returns the exception's class name and message to the
client in the 500 response body. Unhandled exceptions routinely carry sensitive
internals — SQL fragments, file paths, driver/column names, third-party error text —
so this hands reconnaissance detail to any caller who can trigger an error. It directly
violates the repo's own rule (`.claude/rules/security.md`: "Error responses to clients
must not expose stack traces, SQL errors, file paths, or internal service names"). The
full traceback is *already* logged server-side, so the client-facing detail is pure
over-disclosure with no diagnostic value to legitimate users.

## Current state

File: `api/src/life_dashboard/main.py`, lines 430–441:

```python
@app.exception_handler(Exception)
async def _log_unhandled_exception(request: Request, exc: Exception):
    """Catch every unhandled exception, log it with a full traceback, and
    return a generic 500 so the client still gets a proper JSON response."""
    tb = traceback.format_exc()
    logging.getLogger("life_dashboard.errors").error(
        "Unhandled exception on %s %s\n%s", request.method, request.url.path, tb
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},   # ← leaks internal detail
    )
```

The docstring already claims it returns "a generic 500", but the body is not generic.
The server-side `logging...error(...)` line stays — that is the correct place for the
detail. Only the client-facing `content` changes.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run the new test | `cd api && .venv/bin/python -m pytest tests/test_exception_handler.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | pass |
| Lint | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |
| Confirm the leak is gone | `grep -n "type(exc).__name__" api/src/life_dashboard/main.py` | no match |

## Scope

**In scope**:
- `api/src/life_dashboard/main.py` (edit only the `_log_unhandled_exception` response body)
- `api/tests/test_exception_handler.py` (create)

**Out of scope**:
- The server-side logging line — keep it; it is the correct place for the traceback.
- FastAPI's built-in `HTTPException` handling and Pydantic 422 responses — those are
  intentional, structured, client-safe error shapes; do not touch them.
- Any other handler or middleware in `main.py`.

## Git workflow

- Branch: `advisor/005-fix-exception-detail-leak`
- Commit style: conventional commits, e.g.
  `fix(api): return a generic 500 body instead of leaking exception detail`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Return a generic 500 body (keep the server-side log)

Change only the `return JSONResponse(...)` block:

```python
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
```

Leave the `tb = traceback.format_exc()` and the `logging.getLogger("life_dashboard.errors").error(...)`
lines exactly as they are — the detail must still be logged.

Optional (only if trivially clean): include a correlation id so operators can tie a
client-visible 500 to a log line. If you do, generate it, log it alongside the
traceback, and return `{"detail": "Internal server error", "request_id": <id>}`. If this
adds any complexity or a new dependency, **skip it** — the required fix is just the
generic body.

**Verify**: `grep -n "type(exc).__name__" api/src/life_dashboard/main.py` → no match; `grep -n "Internal server error" api/src/life_dashboard/main.py` → one match.

### Step 2: Add a test that a raised exception does not leak its detail

Create `api/tests/test_exception_handler.py`. Build a tiny app that reuses the same
handler and asserts the response body is generic. The cleanest approach is to register
a throwaway route on the real app and hit it with `httpx.ASGITransport` + FastAPI's
`TestClient` is fine too; use whatever's already available (`httpx` is a project dep).

```python
import httpx
import pytest

from life_dashboard.main import app


@pytest.mark.anyio
async def test_unhandled_exception_returns_generic_body():
    # Register a route that raises a secret-bearing exception.
    @app.get("/__test_boom")
    async def _boom():
        raise ValueError("SECRET-INTERNAL-DETAIL-postgres://user:pw@host/db")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/__test_boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "Internal server error"} or body.get("detail") == "Internal server error"
    # The secret text must NOT appear anywhere in the response.
    assert "SECRET-INTERNAL-DETAIL" not in resp.text
    assert "ValueError" not in resp.text
```

Notes:
- `raise_app_exceptions=False` on the transport ensures the ASGI layer lets the app's
  own exception handler produce the 500 (instead of re-raising into the test).
- If the project configures `anyio` with a specific backend, the existing pytest config
  (`anyio[trio]` is a dev dep) should already support `@pytest.mark.anyio`. If the mark
  is unknown, drop it and rely on `asyncio_mode="auto"` (make the function `async def`
  without the mark) — read `conftest.py`/`pyproject.toml` and use whichever the repo's
  other async tests use.
- Importing `app` triggers real app startup imports but not the lifespan DB init (the
  ASGI test client above does not run lifespan by default with `ASGITransport`). If app
  import fails for an unrelated reason, see STOP.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_exception_handler.py -v` → pass.

## Test plan

- `test_unhandled_exception_returns_generic_body` — asserts (a) status 500, (b) body is
  the generic detail, (c) the secret substring and exception class name are absent from
  the response text.
- Verification: `cd api && .venv/bin/python -m pytest` → full suite green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "type(exc).__name__" api/src/life_dashboard/main.py` → no match
- [ ] `grep -n '"Internal server error"' api/src/life_dashboard/main.py` → one match
- [ ] The server-side `logging.getLogger("life_dashboard.errors").error(...)` line is unchanged
- [ ] `cd api && .venv/bin/python -m pytest tests/test_exception_handler.py` → pass
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check src tests` → exit 0
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The handler in `main.py` no longer matches the "Current state" excerpt (drift).
- Importing `life_dashboard.main` in the test fails because the app requires a live DB /
  env at import time — report the error; the test may need env stubs, or the test app
  may need to be constructed differently.
- The test framework rejects both `@pytest.mark.anyio` and the plain-`async def` form —
  report what the repo's other async tests use (from plan 002's `conftest.py`).

## Maintenance notes

- If a correlation-id scheme is later added app-wide, revisit this handler to include the
  id in both the log line and the (still generic) response body.
- Reviewer should confirm no *other* handler or middleware echoes `str(exc)` to clients.
- Follow-up deferred: audit `HTTPException(detail=...)` call sites for any that embed
  raw internal strings (a separate, lower-priority sweep).
