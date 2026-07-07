# Plan 001: Remove committed secrets & data files from the repo, and rotate the leaked credential

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 1977b97..HEAD -- .gitignore cookies.txt life_dashboard.db api/test_boot.db`
> If any of these files changed since this plan was written, compare the
> "Current state" facts against the live repo before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (removing untracked-from-index files; no source-code behavior change)
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `1977b97`, 2026-07-07

## Why this matters

Four files that must never be in version control are currently tracked in git.
The most serious is `cookies.txt`, a Netscape cookie jar that contains a **live
JWT refresh token** — anyone with read access to the repo (or its history) can
exchange it for access tokens and hijack that session until it is revoked. A
committed secret is *burned*: deleting the file does not un-leak it, because it
remains in git history. The fix therefore has two halves: (1) stop tracking the
files and prevent recurrence, and (2) **rotate** the credential so the leaked
token is worthless. The other three files (`life_dashboard.db`, `api/test_boot.db`,
`macbook-air.tail835cbe.ts.net.crt`) are repo-hygiene leaks — a stray SQLite DB
that may contain password hashes/PII, and an internal Tailscale certificate.

## Current state

Confirmed tracked in git (`git ls-files`):

- `cookies.txt` — Netscape cookie jar; line ~6 holds a `refresh_token` value
  (credential type: JWT refresh token). **Do not open, print, or copy the value
  anywhere.** Reference it by location only.
- `life_dashboard.db` — 0-byte SQLite file at repo root.
- `api/test_boot.db` — SQLite file under `api/`.
- `macbook-air.tail835cbe.ts.net.crt` — TLS certificate (public cert; the paired
  `*.key` is already correctly gitignored).

The `.gitignore` today covers `*.key`, `*.pem`, `.env`, `.env.*`, and `api/*.db`,
but **not**: root-level `*.db`, `cookies.txt`, or `*.crt`. Relevant existing lines
(from `.gitignore`):

```
# Environment / secrets
.env
.env.*
!.env.example
*.key
*.pem
...
api/*.db
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| List tracked sensitive files | `git ls-files \| grep -iE '\.(key\|crt\|pem\|db)$\|cookies'` | after the fix: only shows nothing sensitive (see Done criteria) |
| Confirm a file is untracked | `git ls-files --error-unmatch cookies.txt` | after the fix: non-zero exit ("did not match") |

## Scope

**In scope** (the only files you should modify):
- `.gitignore` (edit)
- `cookies.txt` (git-remove from index + delete working copy)
- `life_dashboard.db` (git-remove from index + delete working copy)
- `api/test_boot.db` (git-remove from index + delete working copy)
- `macbook-air.tail835cbe.ts.net.crt` (git-remove from index + delete working copy)

**Out of scope** (do NOT touch):
- `macbook-air.tail835cbe.ts.net.key` — already gitignored; leave it.
- `api/.env.example`, `infra/.env.example` — not part of this plan.
- Git *history* rewriting (filter-repo/BFG) — this is an operator decision, not
  an executor action (see "Operator handoff" below). Do NOT attempt it.

## Git workflow

- Branch: `advisor/001-remove-committed-secrets`
- One commit; message style matches the repo's conventional-commit convention
  (see `git log --oneline -5`), e.g.:
  `chore(security): stop tracking committed secrets and stray db/cert files`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Broaden `.gitignore`

Add these lines to `.gitignore` (under the "Environment / secrets" section, near
the existing `*.key` / `*.pem` lines). Keep the existing `!.env.example` negation
intact.

```
# Secrets / local artifacts that must never be committed
cookies.txt
*.crt
*.db
```

Note: `*.db` is intentionally broad (covers root `life_dashboard.db` and any
future stray DB). The existing `api/*.db` line becomes redundant but leave it —
removing it is out of scope.

**Verify**: `grep -E '^(cookies\.txt|\*\.crt|\*\.db)$' .gitignore` → prints all three lines.

### Step 2: Remove the four files from git tracking and delete the working copies

Run:

```
git rm --cached cookies.txt life_dashboard.db api/test_boot.db macbook-air.tail835cbe.ts.net.crt
rm -f cookies.txt life_dashboard.db api/test_boot.db macbook-air.tail835cbe.ts.net.crt
```

`git rm --cached` unstages them from the index (stops tracking); the `rm` removes
the working-tree copies so they don't linger. If any file is already gone from the
working tree, the `rm -f` is a harmless no-op.

**Verify**: `git ls-files | grep -iE 'cookies\.txt|\.crt$|life_dashboard\.db|test_boot\.db'` → **no output** (exit 1).

### Step 3: Confirm nothing else sensitive remains tracked

**Verify**: `git ls-files | grep -iE '\.(key|crt|pem|db)$|cookies|secret'` → **no output** (the `.key` was never tracked; everything else is now removed).

## Test plan

No code changes, so no unit tests. Verification is entirely via the `git ls-files`
checks above. Do not add tests for this plan.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `git ls-files | grep -iE 'cookies\.txt|\.crt$|life_dashboard\.db|test_boot\.db'` → no output
- [ ] `git ls-files | grep -iE '\.(key|crt|pem|db)$|cookies|secret'` → no output
- [ ] `.gitignore` contains `cookies.txt`, `*.crt`, and `*.db`
- [ ] `git status` shows only `.gitignore` modified and the four files deleted — no other files touched
- [ ] `plans/README.md` status row updated

## Operator handoff — MANDATORY, cannot be done by the executor

Flag these to the human operator in your completion report. They are NOT executor
steps, but the fix is incomplete without them:

1. **Rotate the leaked refresh token.** The token in `cookies.txt` is compromised.
   Revoke it server-side (delete/revoke the matching row in the `refresh_tokens`
   table for the affected user), or — to be safe — rotate `JWT_SECRET_KEY` in the
   deployment's environment, which invalidates all outstanding access tokens.
2. **Decide on history purge.** The files remain in git history. If this repo is
   pushed anywhere shared/public, consider `git filter-repo` (or BFG) to purge
   them, then force-push. If the token has been rotated (step 1), the history
   exposure of `cookies.txt` is defanged, so this is lower urgency.
3. **Check `life_dashboard.db` / `test_boot.db` contents** before assuming they're
   empty — if either held real password hashes or PII, force password resets for
   any affected accounts.

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows any of the four files or `.gitignore` changed since commit
  `1977b97` in a way that conflicts with "Current state".
- `git rm --cached` reports a file is not tracked — report which ones, so the
  operator knows the state changed (do not force anything).
- You are tempted to rewrite git history — that is explicitly out of scope; hand
  it to the operator instead.

## Maintenance notes

- Reviewer should confirm the working tree no longer contains the four files and
  that `.gitignore` will catch future recurrences (`git check-ignore cookies.txt`
  should print `cookies.txt`).
- The `*.db` ignore now also hides intentionally-committed fixture DBs, should any
  be added later — if a test fixture DB is ever needed in-repo, it must be
  force-added with `git add -f` and reviewed carefully.
- Follow-up deferred: git-history purge (operator decision, see handoff).
