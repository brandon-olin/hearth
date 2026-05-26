---
description: Pre-commit review pipeline for Hearth. Runs type checks, linting, and tests, then reviews the diff.
---

## Pre-flight checks

### Changed files
!`git diff --name-only main...HEAD 2>/dev/null || git diff --name-only HEAD~1 2>/dev/null || echo "No diff available"`

### API — type checking and lint
!`cd api && source .venv/bin/activate 2>/dev/null; ruff check src/ 2>&1 | tail -20`

!`cd api && source .venv/bin/activate 2>/dev/null; mypy src/ --ignore-missing-imports 2>&1 | tail -20`

### API — tests
!`cd api && source .venv/bin/activate 2>/dev/null; pytest tests/ -x -q 2>&1 | tail -30`

### Web — type checking
!`cd web && npx tsc --noEmit 2>&1 | tail -20`

### Web — lint
!`cd web && npm run lint 2>&1 | tail -15`

## Diff
!`git diff main...HEAD 2>/dev/null || git diff HEAD~1 2>/dev/null || git diff --cached`

## Review instructions

1. If any pre-flight check failed, list failures first with exact fixes. Do not proceed to code review until you've noted all failures.

2. Review the diff for Hearth-specific issues (in priority order):
   - **Household scoping**: every new query filters by `household_id`
   - **Service layer**: no direct DB calls in router files
   - **Idempotency**: state transitions (marking complete, creating next recurrence) are atomic
   - **Crash risks**: None access on JSONB sub-fields, scalar_one() on optional results, tz-naive datetimes
   - **Security**: missing auth dependency, IDOR on resource IDs
   - **Performance**: N+1 queries, unbounded list queries, large JSONB in list responses
   - **Frontend**: raw fetch to /api/, upload URLs without resolveMediaUrl, hardcoded colors, useParams on dynamic routes

3. For each issue: file, line, what's wrong, specific fix.

4. Verdict: SHIP IT / NEEDS WORK / BLOCKED.

5. If SHIP IT: suggest the commit message in conventional commits format:
   - `feat(domain): description` for new features
   - `fix(domain): description` for bug fixes  
   - `chore: description` for migrations, tooling, docs
   - `refactor(domain): description` for non-functional changes

6. Remind: update `claude-progress.txt` and `feature_list.json` before committing.
