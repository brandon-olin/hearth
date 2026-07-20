# ADR-015: Reconcile native Postgres enums with the ORM models

**Status:** Accepted
**Date:** 2026-07-20
**Deciders:** Brandon
**Related:** ADR-014 (SQLite schema evolution) — this removes a divergence class that ADR-014's dual-engine model exposes

---

## Context

On 2026-07-20 the Railway deploy failed. Migration `0046` compared
`collections.domain` against a VARCHAR-bound parameter:

```
operator does not exist: collection_domain = character varying
```

The immediate cause was a mistyped column in the migration's Core `sa.table()`
(fixed by declaring `sa.Enum(..., name="collection_domain")`, so the asyncpg
dialect renders `$1::collection_domain` rather than `$1::VARCHAR`). But the
reason it reached production undetected is structural, and that is what this
ADR addresses.

**The models and the migration history disagree about seven columns.** The
migrations create native Postgres enum types; the models declare
`SaEnum(..., native_enum=False)`, i.e. VARCHAR + CHECK. Verified against a
migration-built database (`information_schema.columns` where
`data_type = 'USER-DEFINED'`):

| Table | Column | Native type | Null | Default | Values |
|---|---|---|---|---|---|
| `collections` | `domain` | `collection_domain` | NO | — | notes, documents |
| `documents` | `kind` | `document_kind` | NO | `'page'` | page, template |
| `exercise_entries` | `type` | `exercise_type` | NO | — | strength, cardio, hiit, flexibility, other |
| `goals` | `priority` | `priority_level` | YES | — | low, medium, high |
| `household_memberships` | `role` | `membership_role` | NO | `'member'` | owner, admin, member, viewer, agent |
| `projects` | `status` | `project_status` | NO | `'active'` | backlog, active, on_deck, in_progress, complete, archived |
| `todos` | `priority` | `priority_level` | YES | — | low, medium, high |

Note `priority_level` is shared by two columns — it can only be dropped after
both are converted.

### Why this is worth fixing rather than documenting

A database built by `Base.metadata.create_all()` gets VARCHAR for these
columns. A database built by replaying migrations gets native enums.
**Production is the second kind; most local verification is the first kind.**
Any migration that touches one of these seven columns through a Core table can
therefore pass every local check and still fail the Railway pre-deploy. That is
precisely what happened with `0046`, and six more columns remain exposed to it.

Documenting the drift (as the first pass did, in `api/CLAUDE.md`) is a
mitigation whose cost grows with every new drifted column and which depends on
the reader remembering to check a table. It does not remove the trap.

### Constraints

- The Railway deployment is Brandon's own single-household instance — there are
  no external users yet. Its data is worth preserving but is not
  irreplaceable, so this is a correctness exercise rather than a
  high-stakes data migration. Sizing the risk honestly matters here: it is the
  argument for doing the conversion now, while it is cheap, rather than after
  there are households that cannot be rebuilt.
- Per ADR-014, SQLite is a first-class tier. Whatever is chosen must not widen
  the gap between the engines.
- Three columns carry server defaults. Postgres refuses
  `ALTER COLUMN ... TYPE` while a default is attached, so each needs the
  default dropped and re-added around the change.

---

## Decision

**Convert all seven columns to VARCHAR + CHECK on Postgres (migration `0047`),
matching what the models already declare and what SQLite already produces.**

The models need no change — they are already correct. This migration makes the
database match them.

---

## Options Considered

### Option A: Convert Postgres to VARCHAR + CHECK *(chosen)*

Per column: drop the default if present, `ALTER COLUMN ... TYPE varchar(n)
USING col::text`, re-add the default, add a CHECK constraint. Then drop the now
unreferenced types.

- Both engines end up structurally identical, so `create_all` and
  migration-replay converge. The failure class disappears rather than being
  documented.
- Adding an enum value later becomes an ordinary migration (drop and re-add a
  CHECK) instead of `ALTER TYPE ... ADD VALUE`, which is awkward under
  Alembic's transactional DDL.
- Cost: a seven-column data migration against live production, with the
  default-detach dance on three of them.
- Loses native enum type-safety. CHECK constraints still reject invalid values,
  so the enforcement remains; what is lost is the type appearing in
  `pg_type` and the ordering semantics of `enumsortorder` — neither is used
  anywhere in the codebase.

### Option B: Change the models to `native_enum=True`

Leave the database alone; make the seven model declarations match production,
adding an explicit `name=` to each.

- Much smaller — seven model edits, no data migration, no production risk.
- Rejected because it entrenches the divergence rather than removing it.
  Postgres keeps native enums, SQLite keeps VARCHAR, and every future migration
  touching these columns still has to get the bind type exactly right. It fixes
  the mismatch on paper while leaving the trap armed.
- Also makes future enum value additions painful, as above.

### Option C: Squash the migration history to a clean baseline

Collapse `0001`–`0046` into one baseline reflecting the current schema, with
the enums already declared as VARCHAR.

- **Rejected as a substitute, not as an idea.** A squash lands on existing
  databases via `alembic stamp`, which runs no DDL. The deployed database would
  keep its native enum columns while the new baseline asserts they are VARCHAR
  — creating exactly the silent model-vs-reality drift this ADR exists to
  remove, but worse, because the baseline would be the thing lying.
- A squash only benefits fresh installs. Any existing database needs a real
  `ALTER` regardless, which is Option A.
- Caveat, given there are no external users: the deployed instance *could*
  instead be rebuilt from a squashed baseline and reseeded, sidestepping the
  conversion entirely. That is a legitimate option today and will stop being
  one the moment there is a household whose data cannot be recreated. It was
  not chosen because `0047` is already written and verified, and because the
  model/database agreement it establishes is needed either way.
- Still worth doing **after** `0047`, and `0047` makes it safer: once the schema
  matches the models, a squashed baseline can be generated from the models with
  far more confidence. The history has independent reasons to be squashed — a
  dead Logseq detour (`0003`/`0004` create then retire tables) and two
  catch-up migrations (`0024b`, `0029b`) that exist because formal migrations
  had already fallen behind reality.

---

## Consequences

**Good**

- `create_all`-built and migration-built Postgres databases converge, so local
  verification becomes meaningful for this class of change.
- The `api/CLAUDE.md` drift table can be deleted rather than extended.
- Future enum value changes are ordinary migrations on both engines.

**Costs and risks**

- One data migration touching seven columns across six tables. Mitigated by
  `USING col::text` (a total, value-preserving conversion), by rehearsing on a
  throwaway replay before pushing, and — for now — by the deployment being a
  single personal instance.
- The models needed one change after all, discovered during implementation.
  `SaEnum(..., native_enum=False)` emits a bare `VARCHAR(n)` and **no CHECK** —
  `create_constraint` has defaulted to `False` since SQLAlchemy 1.4. Converting
  the columns without adding constraints would therefore have dropped all
  database-level value enforcement, including on `household_memberships.role`,
  a permissions column the agent surface can write. Each of the seven
  declarations now carries `name="<type>"` and `create_constraint=True`, so
  `create_all` emits `CONSTRAINT <type> CHECK (col IN (...))` — byte-identical
  to what `0047` produces, constraint names included. Verified by compiling
  both and diffing all seven.
- Orphaned types from earlier schema churn (`note_kind`, `actor_type` — their
  columns disappeared when `0010` and `0044` recreated those tables) may still
  exist in `pg_type`. `0047` drops them if present.

**Neutral**

- SQLite needs no type conversion — `create_all` already produces VARCHAR
  there — but `0047` does still add the CHECK constraints on that engine via
  `batch_alter_table`. Without that, a SQLite database created before this
  revision would lack constraints that one created after it has, which is the
  same drift in miniature. So the migration does less work on SQLite, but it is
  not a no-op.

---

## Action Items

1. Migration `0047` — convert the seven columns, drop the six types, drop
   orphaned types. *(this change)*
2. Verify on a migration-built Postgres replay that
   `information_schema.columns` reports zero `USER-DEFINED` columns.
3. Delete the drift table from `api/CLAUDE.md` once 2 passes; keep the
   asyncpg bind-type guidance, which remains true for other native types.
4. *(separate, later)* Reconsider the squash now that schema and models agree.
