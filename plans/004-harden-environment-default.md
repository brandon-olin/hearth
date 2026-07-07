# Plan 004: Harden the `environment` setting so production fails safe

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- api/src/life_dashboard/core/settings.py api/src/life_dashboard/main.py api/src/life_dashboard/auth/router.py api/src/life_dashboard/households/router.py`
> If any changed since this plan was written, compare the "Current state" excerpts
> against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED (changes a default that local dev relies on — dev must now set `ENVIRONMENT=development` explicitly; get the dev-onboarding update right or you break local runs)
- **Depends on**: plans/002-verification-baseline.md (for the test)
- **Category**: security
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

`environment` defaults to `"development"` (`core/settings.py:71`). This single value
is a fail-**open** switch: it gates whether Swagger/ReDoc docs are exposed
(`main.py:415-416`), whether the dev impersonation endpoint
`POST /households/dev/impersonate/{id}` is live (`households/router.py`, checked via
`settings.environment != "development"`), and whether the refresh cookie gets the
`Secure` flag (`auth/router.py:55` `_COOKIE_SECURE = settings.environment != "development"`).
A production deployment that forgets to set `ENVIRONMENT` therefore silently ships with
API docs public, **admin-usable impersonation enabled**, and refresh cookies sent
without `Secure`. Security-critical switches should fail *closed*: the safe default is
"treat as production unless told otherwise."

This plan flips the default to a hardened value and adds a boot-time guard so a
dangerous configuration cannot start silently. It intentionally keeps the change small
and reversible, and updates the local-dev entrypoints so developers still get docs and
easy iteration.

## Current state

- `core/settings.py:71`: `environment: str = "development"` (pydantic-settings reads
  `ENVIRONMENT` from env/.env; the field default is the fallback).
- `main.py:415-416`:
  ```python
  docs_url="/docs" if settings.environment == "development" else None,
  redoc_url="/redoc" if settings.environment == "development" else None,
  ```
- `auth/router.py:55`: `_COOKIE_SECURE = settings.environment != "development"` (used at
  lines 63 and 74 for the refresh cookie `secure=` flag).
- `households/router.py`: the impersonation endpoint raises 403 unless
  `settings.environment == "development"` (dev-only gate).
- Local dev is started via `make api` (`cd api && .venv/bin/uvicorn ... --port 1339`)
  and the always-on launchd service on port 1338. `api/.env.example` documents settings.
- There is a `deployment_tier`-style concept referenced in the audit; **verify** whether
  `settings.py` has a separate `deployment_tier` field before relying on it (grep in Step 1).

The important behavioral contract to preserve: **local developers must still get
`/docs` and non-Secure cookies over http://localhost.** Achieve that by setting
`ENVIRONMENT=development` in the dev entrypoints, not by keeping an unsafe default.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Inspect settings field | `grep -n "environment" api/src/life_dashboard/core/settings.py` | shows the default line |
| Run the new test | `cd api && .venv/bin/python -m pytest tests/test_settings_environment.py -v` | pass |
| Full suite | `cd api && .venv/bin/python -m pytest` | pass |
| Lint | `cd api && .venv/bin/python -m ruff check src tests` | exit 0 |

## Scope

**In scope**:
- `api/src/life_dashboard/core/settings.py` (edit the default)
- `Makefile` (edit the `api` target to export `ENVIRONMENT=development` for local dev)
- `api/.env.example` (document that `ENVIRONMENT` defaults to `production` and dev must set it)
- `infra/launchd/*` **only if** the launchd plist template sets env vars for the dev API — otherwise note it in the report for the operator (see STOP/handoff)
- `api/tests/test_settings_environment.py` (create)

**Out of scope**:
- The docs-gating / cookie / impersonation logic itself — only the *default* and the
  dev entrypoints change; the comparison expressions stay `== "development"`.
- Introducing a full enum for environments — keep it a string; a boot guard is enough.

## Git workflow

- Branch: `advisor/004-harden-environment-default`
- Commit style: conventional commits, e.g.
  `fix(config): default environment to production so prod fails safe`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm the surface before editing

Run these and read the results so your change is complete:

```
grep -rn "settings.environment" api/src/life_dashboard/
grep -n "deployment_tier" api/src/life_dashboard/core/settings.py
```

Note every place `settings.environment` is compared — the default flip must not break
any of them. (Expected: the three gates named in "Current state".) If `deployment_tier`
exists, note its default; the boot guard in Step 3 can use it, otherwise skip that
refinement.

### Step 2: Flip the default to a safe value

In `core/settings.py:71`, change:

```python
environment: str = "development"
```
to:
```python
environment: str = "production"
```

**Verify**: `grep -n 'environment: str = "production"' api/src/life_dashboard/core/settings.py` → one match.

### Step 3: Add a boot-time guard (defense in depth)

In `main.py`, inside the app startup/lifespan (near where it logs
`"Starting life_dashboard API environment=%s"`, ~line 76), add a warning-or-fail guard.
Because the default is now `production`, the risk inverts: warn loudly if something
starts in `development`. Add:

```python
if settings.environment not in ("development", "production"):
    raise RuntimeError(
        f"Invalid ENVIRONMENT={settings.environment!r}; expected 'development' or 'production'"
    )
if settings.environment == "development":
    logger.warning(
        "Running in DEVELOPMENT mode — API docs, dev impersonation, and non-Secure "
        "cookies are ENABLED. Never use this in a deployed environment."
    )
```

(This makes an unsafe mode conspicuous in logs and rejects typos like `ENVIRONMENT=prod`
that would otherwise silently be treated as production — which is safe — but a typo like
`ENVIRONMENT=dev` must NOT accidentally enable dev mode, which this guard enforces by
rejecting anything that isn't exactly the two known values.)

**Verify**: covered by the test in Step 5.

### Step 4: Keep local development working

Local dev must explicitly opt into development mode now. Update the `api` target in the
`Makefile` so `make api` exports it:

```makefile
api:
	cd api && ENVIRONMENT=development .venv/bin/uvicorn life_dashboard.main:app --reload --port 1339
```

Also update `api/.env.example`: near the environment/app settings, ensure there is an
explicit, documented line, e.g.:

```
# Environment: "production" (default, hardened) or "development" (enables /docs,
# dev impersonation, and non-Secure cookies). Local development should set this to
# development. Deployed environments should leave it as production.
ENVIRONMENT=development
```

If the always-on launchd service (port 1338) is meant for local use and relies on the
old default, it must also set `ENVIRONMENT=development` — but modifying an installed
launchd plist is an operator action. Check whether a plist **template** under
`infra/launchd/` sets env vars; if so, add `ENVIRONMENT=development` there, otherwise
add an item to the operator handoff.

**Verify**: `grep -n "ENVIRONMENT=development" Makefile` → one match in the `api` target.

### Step 5: Add a test pinning the safe default

Create `api/tests/test_settings_environment.py`:

```python
from life_dashboard.core.settings import Settings


def test_environment_defaults_to_production(monkeypatch):
    # With no ENVIRONMENT set, the default must be the hardened value.
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    s = Settings(database_url="sqlite+aiosqlite:///:memory:")
    assert s.environment == "production"
```

If `Settings` requires other mandatory fields to instantiate, supply them as keyword
args (read `settings.py` for required fields; `database_url` is required per line 12).
If `Settings` reads a real `.env` that sets `ENVIRONMENT`, use `monkeypatch` /
`_env_file=None` to isolate — the point is that the *field default* is `production`.

**Verify**: `cd api && .venv/bin/python -m pytest tests/test_settings_environment.py -v` → pass.

## Test plan

- `test_environment_defaults_to_production` — pins the security-relevant default so a
  future refactor can't silently reintroduce the fail-open behavior.
- Verification: `cd api && .venv/bin/python -m pytest` → full suite green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'environment: str = "production"' api/src/life_dashboard/core/settings.py` → one match
- [ ] `grep -n "ENVIRONMENT=development" Makefile` → present in the `api` target
- [ ] `api/.env.example` documents the `ENVIRONMENT` default and dev opt-in
- [ ] `cd api && .venv/bin/python -m pytest tests/test_settings_environment.py` → pass
- [ ] `cd api && .venv/bin/python -m pytest` → full suite passes
- [ ] `cd api && .venv/bin/python -m ruff check src tests` → exit 0
- [ ] No out-of-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 reveals `settings.environment` is compared anywhere with logic that would
  *break* under a `production` default in local dev beyond the three known gates (e.g.
  a DB bootstrap that only runs in development) — report the extra site before flipping.
- `make api` (or the launchd service) cannot be made to run in development mode without
  touching an installed/generated file outside the repo — hand that to the operator.
- The test cannot isolate the default because `Settings` force-loads a `.env` with
  `ENVIRONMENT` set — report it; the field-default assertion may need `_env_file=None`.

## Operator handoff

Include in your completion report:
- If an installed launchd plist (port 1338 service) exists on the operator's machine, it
  must be re-generated/reinstalled so the local always-on API runs with
  `ENVIRONMENT=development`, or it will now start in production mode (no `/docs`, Secure
  cookies over http will not be sent by the browser → login may appear broken locally).
- All **deployed** environments must have `ENVIRONMENT=production` (now the default, so
  this is satisfied unless they explicitly set development).

## Maintenance notes

- This makes `production` the default across all three deployment tiers, which matches
  the "portable across tiers / privacy by default" principle in the root `CLAUDE.md`.
- Reviewer should confirm no code path assumes `environment == "development"` as a
  *default-true* condition anywhere (the flip changes the default answer to those
  checks from true to false).
- Follow-up deferred: consider promoting `environment` to a validated `Literal`/enum in
  a later pass so the boot guard becomes unnecessary.
