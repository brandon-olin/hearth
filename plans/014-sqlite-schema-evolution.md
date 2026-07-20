# ADR-014: SQLite schema evolution for the desktop tier

**Status:** Proposed
**Date:** 2026-07-20
**Deciders:** Brandon
**Supersedes:** the "unblock the free SQLite/desktop tier" direction option (`plans/README.md:102`, `ROADMAP.md:107`)

---

## Context

The Tauri desktop app is the first-touch product for **non-technical households evaluating
Hearth before paying**. It ships SQLite (`lib.rs` hardcodes
`sqlite+aiosqlite:///{app_data}/life_dashboard.db`), which is the right call: no daemon, no
port, no install step, single-file backup. Bundling Postgres would mean `initdb` on first
run, data-directory lifecycle, and major-version upgrades on machines we cannot inspect.

*(Correcting the record: an earlier discussion assumed Postgres requires Docker on a user
machine. It does not — Postgres.app, Homebrew, and the EDB installer all work natively, and
`infra/local.env.example` already documents native local Postgres. The SQLite decision stands
on install-friction and bundle-lifecycle grounds, not on that false premise.)*

**SQLite installs never run Alembic.** `api/migrations/env.py:80` hard-blocks it:

```python
def run_migrations_online() -> None:
    if _is_sqlite():
        # SQLite tier: Alembic migrations are Postgres-specific.
        print("[alembic] SQLite detected — skipping migration history. ...")
        return
```

Schema is instead produced by `create_all()` plus `_patch_sqlite_schema()`
(`core/database.py`), whose documented limitations are load-bearing:

- UNIQUE columns **skipped entirely** (warning logged, boot continues)
- NOT NULL columns added as **nullable**
- Primary keys skipped; no drops, renames, or type changes
- **No data backfills, ever**

Against 49 migrations (single linear chain, root `0001` → head `0045`), of which roughly 25
run `op.execute`/backfills and ~30 do alter/drop/rename.

### Why this is urgent now

The failure splits by install age:

| Scenario | Outcome |
|---|---|
| **Fresh** Tauri install | Largely correct — `create_all()` builds current ORM metadata, UNIQUE constraints included, and there is no data to backfill. |
| **Updated** Tauri install | New nullable columns appear; **everything else silently does not happen.** New UNIQUE constraints skipped, renames never applied, backfills never run. |

The second row is the trial-to-paid population.

This has already bitten twice, both recorded in-repo:

1. **`collection.kind`** — migration `0032`'s backfill is Postgres-only (native JSONB
   operators), leaving SQLite installs at `kind=NULL`, which "silently breaks the coach's
   narrative fetch and the journal signal extractor." Fixed by hand-writing a Python twin,
   `backfill_journal_kind` (`domains/collections/service.py:95`).
2. **Plan 011's unique index** — `plans/README.md:31` notes "local is SQLite (schema via
   `create_all`, alembic no-op — fresh local DBs get the index from the model)."

Two consequences follow:

- **The twin-hook tax is unbounded.** Every future data migration needs a hand-written
  idempotent boot hook or Tauri users get silent NULLs. Two implementations per change,
  and forgetting fails quietly.
- **Constraint drift threatens conversion.** Because UNIQUE is skipped on upgrade, a Tauri
  user can accumulate duplicate rows Postgres would reject. Their export→cloud import then
  fails at precisely the moment they are trying to pay us.

### Constraints

- **Production Postgres auto-migrates on deploy** — `api/railway.json` sets
  `preDeployCommand: "alembic upgrade head"`. Anything touching migration history touches prod.
- **Zero external users.** Brandon's machine only. This is the cheapest this fix will ever be,
  and it gets permanently more expensive once real installs exist.

---

## Decision

Adopt **Option B2 (stamp-at-head, forward-only)** as the mechanism, with
**Option D (export/import)** as the escape hatch and paid-conversion path.

Concretely:

1. Fresh SQLite install: `create_all()` as today, then `alembic stamp head`.
2. Remove the SQLite hard-block in `env.py`; enable `render_as_batch` on SQLite.
3. Subsequent app updates run **only new migrations** forward, in batch mode.
4. Delete `_patch_sqlite_schema()` — it is the drift generator.
5. Build versioned export/import as the recovery path when a migration cannot be
   expressed safely on SQLite.

Historical migrations `0001`–`0045` **never run on SQLite** and therefore need no audit.
Production Postgres is untouched.

---

## Options Considered

### Option A: Run Alembic on SQLite, audit all 49 migrations

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Cost | Audit 49 migrations for PG-only `op.execute` SQL |
| Risk | Batch mode rebuilds tables (copy/rename) on user machines |
| Familiarity | Standard Alembic practice |

**Pros:** One literal history for both engines; maximum fidelity.
**Cons:** Historical migrations reference tables/columns later dropped; auditing them buys
nothing, since no SQLite install will ever replay them. Existing installs still need stamping.

### Option B1: Squash a shared baseline for both engines

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Must stamp live prod Postgres at the new baseline |
| Risk | **Touches a prod DB that auto-migrates on deploy** |
| Familiarity | Common practice |

**Pros:** Deletes 49 files of carrying cost; single clean history.
**Cons:** The only benefit over B2 is tidiness, paid for with risk against the one database
holding real data. `railway.json` runs `upgrade head` automatically on push.

### Option B2: `create_all` + stamp head, forward-only *(chosen)*

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | ~1 day: env.py change, stamp call, batch mode, delete patcher, CI test |
| Risk | Low — prod untouched, no historical replay |
| Familiarity | Standard |

**Pros:** Achieves the actual goal (future migrations apply to SQLite) at the lowest cost.
Fresh and upgraded installs converge on identical schema. Kills the twin-hook tax and
`_patch_sqlite_schema` drift together. No prod exposure.
**Cons:** Migration history is not literally shared — a SQLite DB's `alembic_version` starts
at whatever head it was created under. New migrations must be written SQLite-safe going
forward (new discipline, see Consequences).

### Option C: Keep `create_all`, formalize the twin-hook pattern

| Dimension | Assessment |
|---|---|
| Complexity | Low now, compounding later |
| Cost | Two implementations per data migration, forever |
| Risk | **Silent** failure when forgotten |

**Pros:** Zero immediate work; `backfill_journal_kind` proves the pattern works.
**Cons:** This is the status quo, and it has already failed once. Codifying a policy whose
failure mode is silent NULLs in the conversion-critical tier is a slow leak.

### Option D: Export/import as upgrade path *(adopted as complement, not alternative)*

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Shared with the paid-tier build |
| Risk | Lossy-export risk; slow on large DBs |

**Pros:** One code path serves **app upgrade, self-host→cloud migration, and the open-data
initiative** already tracked in `plans/open-hearth.md`. The escape hatch and the revenue path
are the same build.
**Cons:** Too slow to be the *primary* upgrade mechanism for routine schema changes; still
needs schema versioning. Correct as a safety net, wrong as the default.

---

## Trade-off Analysis

The decisive axis is **cost paid against risk carried, given zero users.**

A and B1 both spend real effort — and B1 spends *prod risk* — to buy history tidiness that
changes no user-visible behavior. B2 buys the entire behavioral benefit (migrations actually
apply on SQLite) for a fraction of the cost, because the historical migrations are dead code
from SQLite's perspective. There is no scenario in which a SQLite install replays `0001`.

C is cheapest today and most expensive cumulatively, with the worst failure mode: silence.

D is not a competitor to B2. It answers a different question — "what happens when a migration
*cannot* be expressed safely on SQLite" — and it is work already on the roadmap. Adopting both
means the routine path is cheap (B2) and the exceptional path is already built (D).

The zero-user window is doing real work in this analysis. At 100 installs, B2's stamping story
becomes a data-migration problem and C's inertia becomes much harder to escape.

---

## Consequences

**Easier**

- Future migrations apply to both tiers from one definition; twin hooks stop accruing
- `_patch_sqlite_schema()` and its silent UNIQUE-skipping disappear
- Fresh and upgraded SQLite installs converge on identical schema
- Constraint parity restored, so Tauri→cloud export/import stops being a conversion cliff

**Harder**

- **New discipline:** every migration must be SQLite-safe. Batch mode covers most ALTER
  limitations, but raw `op.execute` with Postgres-specific SQL needs a dialect guard. This
  belongs in `api/CLAUDE.md` alongside the existing idempotency rules.
- Migration authoring now has two targets to think about rather than one

**To revisit**

- The `pgloader` recommendation in `env.py`'s SQLite message is obsolete once D exists
- Whether to squash Postgres history (B1) as separate, deliberate work when prod can take
  a stamping window — explicitly *not* bundled here
- SQLite full-text search: conversation search degrades to ILIKE (`ai/service.py:461`),
  losing stemming and phrase ranking. FTS5 is the fix. **Re-scoped to post-launch retention,
  not a launch or conversion risk** — see "FTS5 scope" below.

---

## Action Items

1. [ ] Remove the `_is_sqlite()` early-return in `api/migrations/env.py:80`
2. [ ] Add `render_as_batch=_is_sqlite()` to `do_run_migrations`'s `context.configure`
3. [ ] After `create_all_tables()` on a fresh SQLite DB, run `alembic stamp head`
4. [ ] Delete `_patch_sqlite_schema()` and its call site in `core/database.py`
5. [ ] CI test: build a SQLite DB from `create_all` + stamp, then `upgrade head` against a
       new migration and assert the column/constraint lands
6. [ ] Document the SQLite-safe migration rules in `api/CLAUDE.md`
7. [ ] **Fold `backfill_journal_kind` into a migration and delete the boot hook**
       (`main.py:310`). *Resolved 2026-07-20 — see "Why folding is safe" below.*
8. [ ] Correct the obsolete `pgloader` line in the `env.py` SQLite message
9. [ ] *(Option D, separate track)* Versioned household export/import — coordinate with
       `plans/open-hearth.md` exports rather than building twice

---

## Resolved sub-decisions

### Why folding `backfill_journal_kind` into a migration is safe

The hook (`domains/collections/service.py:96`, called from `main.py:310`) does two jobs:
(1) tag existing `kind=NULL` collections that look like journals, (2) seed a journal
collection for households lacking one.

Job 2 looked like an ongoing invariant, which would have argued for keeping the hook. It is
not. `seed_default_journal_collection` is already called at **both** household-creation
points — `auth/router.py:149` (signup) and `setup/router.py:111` (first-run setup) — so every
new household gets a journal collection at creation. Both jobs therefore only ever touch
households predating the `kind` column: purely historical work.

Folding it in also removes a per-boot scan of every household with a query each — an N+1 that
is trivial on a single-household desktop install and real on multi-household cloud.

The only capability lost is self-healing against a *future* code path that creates a household
without seeding a journal collection. That is speculative, and the correct guard is a test or
a DB constraint, not scanning every household on every boot forever.

### FTS5 scope

Re-scoped from launch/conversion risk to **post-launch retention**, for two reasons.

**Volume.** A two-week trial user accumulates a few hundred messages; ILIKE across a few
hundred rows is instant and the quality gap is invisible. The gap only shows at thousands of
messages — a months-long user who has already converted or churned.

**Reach is narrower than it first appeared.** FTS5 would only improve **AI conversation
search** (`ai_messages`). Document search already uses `cast(editor_json, SaText).ilike(...)`
on *both* engines (`documents/service.py:394`), so it is equally substring-based on Postgres —
not a SQLite deficiency at all.

**This makes FTS5 dependent on an unresolved product decision.** Its entire value on the
SQLite tier is gated on AI being *used* there. If BYOK is not surfaced on Tauri (open question
— see below), `ai_messages` stays near-empty on that tier and FTS5 buys essentially nothing.
**Resolve the BYOK-on-Tauri question before scheduling FTS5.**

Counterweight, so it is not dismissed outright: the coach's pitch is "it remembers and
connects things," and weak search undercuts that for the most engaged users. Worth doing
eventually — just not before 014, and not as a launch gate.

---

## Related decision: BYOK surfacing

*Resolved 2026-07-20.* BYOK stays **available on every free tier** (Tauri and self-hosted) but
is **not surfaced in onboarding** — it lives in Settings only. On paid tiers the AI settings
section is hidden entirely, since managed AI is built in.

This keeps the paid differentiator as *convenience* ("AI that just works, no key") rather than
*access*, which preserves the `CLAUDE.md` open-core rule that basic AI/BYOK hooks are always in
the open core, without putting an API-key prompt in a non-technical user's first-run path.

Consequence for FTS5 (above): AI adoption on the SQLite tier is expected to be low but nonzero,
so `ai_messages` volume there stays small — reinforcing FTS5 as post-launch retention work
rather than a launch gate.

*Out of scope here, flagged for later:* per-user AI usage economics on paid tiers, and vetting
the agent skill/harness against that budget.

---

## Appendix: parity findings verified and closed

Recorded so they are not re-audited from scratch.

- **JSONB is never used as a column type.** Zero `dialects.postgresql` imports repo-wide;
  every model uses generic `sqlalchemy.JSON` (`habits.cadence`, `todos.recurring`,
  `documents.editor_json`, `budget.split_config`, PAT scopes). "JSONB" in docstrings is
  intent vocabulary, not a type. **The column layer is fully portable** — earlier concern
  about JSONB degradation on SQLite was based on comments, not types, and is withdrawn.
- **`ai/service.py:461`** already branches `if dialect == "sqlite"` → ILIKE fallback. Handled,
  degraded (see Consequences), not broken.
- **`documents/service.py:394`** uses `cast(editor_json, SaText).ilike(...)` — generic
  SQLAlchemy, portable on both engines despite the "Postgres JSONB→text cast" comment.
- **`budget/models.py:342`** declares both `postgresql_where` and `sqlite_where`. Handled.
- **`domains/collections/service.py:95`** `backfill_journal_kind` is already backend-agnostic.

Net: query-layer parity is in good shape. The problem was never parity — it was schema
evolution.
