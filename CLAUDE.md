# life_dashboard — Project Context for Claude

**Read this first.** This file is the canonical context for the life_dashboard
project. It's intentionally written so a fresh Claude thread can pick up
exactly where we left off without re-deriving any decisions or asking the
user to re-explain themselves.

User's name: **Brandon**.

---

## What this project is

A local-first life-management system for Brandon's household. All core data
(plans, tasks, notes, calendar, recipes, contacts, habits, goals) lives in a
self-hosted Postgres on Brandon's NAS. A local LLM on Brandon's gaming PC
acts as the reasoning/automation engine. A web UI on the NAS is the day-to-day
interface for Brandon and his family.

Goals:

- **Privacy-focused**: data never leaves Brandon's hardware. Remote access is
  via Tailscale, not the public internet.
- **Governed AI**: an LLM agent assists with reading and modifying data, but
  never speaks SQL — only structured high-level operations with audit trails
  and human approval for destructive ops.
- **Extensible**: new domains (garden, orchard, home projects, travel) get
  added as backend modules. The agent's action vocabulary grows with them.
- **Interop-friendly**: where possible, the data model speaks open standards
  (iCal-compatible calendar, vCard-compatible contacts, markdown notes).
  This keeps doors open to Home Assistant integration and CalDAV/CardDAV sync.

---

## Hardware / network topology

- **NAS** (Synology): runs Docker. Already has a `postgres-1` container
  serving Postgres 16 with the `life_dashboard` database (owner: `brandon`).
  Will eventually also run the FastAPI backend and the Next.js frontend
  as additional containers on the same internal Docker network. Caddy
  terminates TLS using a Tailscale cert.
- **Gaming PC**: runs the local LLM (Ollama / llama.cpp / LM Studio TBD).
  Reaches the NAS over LAN/Tailscale. Hosts the agent code that calls
  the backend's MCP server.
- **Mac (Brandon's laptop)**: development machine. Monorepo lives at
  `~/Code/Personal/life-dashboard/`. Brandon also uses VSCode + Claude Code
  here for actual code construction.
- **Family phones**: install Tailscale, open the responsive web UI by URL.
  No native app, no offline sync (deliberately deferred — see below).

---

## Stack decisions (locked in)

| Layer | Choice | Why |
|---|---|---|
| Database | Existing Postgres 16 in `postgres-1` | Already running, owns the data |
| Backend lang | Python 3.12 | Best LLM/agent ecosystem; HA-friendly (HA is Python) |
| Backend framework | FastAPI | Auto-generates OpenAPI for typed clients + MCP tooling |
| ORM | SQLAlchemy 2.0 (async) | Schema reflection from existing DB; mature |
| Migrations | Alembic | Standard SQLAlchemy companion |
| Validation | Pydantic v2 | Native to FastAPI |
| Auth | argon2 + JWT + refresh tokens | Individual passwords; magic links later |
| Frontend | Next.js (App Router) | Largest ecosystem; PWA-ready for mobile |
| Frontend styling | Tailwind + shadcn/ui | Fast dev; good defaults |
| Frontend data | TanStack Query + OpenAPI-typed client | End-to-end types via codegen |
| Deployment | docker-compose on the NAS | Lives next to `postgres-1` |
| Remote access | Tailscale (responsive web) | No public internet exposure |
| Repo layout | Monorepo (flat, no Nx/Turborepo) | One root, easy VSCode + AI context |

The backend's service layer (`api/src/life_dashboard/core/`) is
**deliberately FastAPI-free** so it can be reused by the MCP server, and
potentially extracted as a Home Assistant custom integration later.
HTTP routers and MCP tools both call into `core/`. `core/` imports nothing
from `api/` or `mcp/`.

---

## Architectural principles

1. **Local-first**: data never leaves Brandon's hardware. Period.
2. **Governed AI**: LLM never speaks SQL. Operations are a fixed vocabulary
   with input validation, role-based authorization, audit logs, and
   approval gates for destructive/bulk actions.
3. **Multi-user from day one**: every root entity carries `household_id` and
   `created_by_user_id`. Schema is ready for family sharing now even if
   only Brandon uses it for a while.
4. **Open-format interop**: iCal-compatible calendar, vCard-compatible
   contacts, markdown for notes. Don't lock data behind proprietary shapes.
5. **Audit everything**: every write through the backend produces an
   `audit_log` row with a structured diff and the actor's identity.

---

## Decisions explicitly rejected (don't relitigate)

- **Grocy** — evaluated and rejected. Too heavy for household use; brings
  a second database and service for features (pantry inventory, meal planning)
  Brandon doesn't currently want. life_dashboard owns recipes and grocery
  lists directly.
- **Building inside Home Assistant's UI** — rejected. HA's frontend stack is
  optimized for device control, not life-management UX. life_dashboard is
  a standalone Next.js app that *consumes* HA data (weather, presence,
  sensor states) via HA's REST/WebSocket API for specific widgets.
- **Native mobile app** — deferred indefinitely. Responsive web over
  Tailscale is the mobile/remote-access plan.
- **ElectricSQL / PowerSync / offline-first sync** — deferred indefinitely.
  Only revisit if responsive-web-over-Tailscale produces real pain.
- **Direct LLM database access** — never. The LLM only sees the MCP tool
  vocabulary.
- **Separate chores entity** — not needed. Recurring chores fit `habits` +
  `habit_occurrences`; one-off chores fit `todos`; chore projects fit
  `todos.parent_id` hierarchies.
- **Multi-tenant SaaS model** — explicitly not. This is for one household.
  Multi-user means multiple humans in one household, not multiple tenants.

## Decisions explicitly deferred (revisit later)

- **Magic-link / passwordless auth** — passwords first, add magic links as
  a parallel auth method when convenient. Schema doesn't need changes.
- **MQTT event bus + Home Assistant custom integration** — Phase 4.
  The backend's `events/` module is structured to make this a drop-in
  later (currently in-process only).
- **Migrating legacy `text[]` tags on `notes.tags` and `recipes.tags`** to
  the normalized `tags` + `taggings` tables. New tags table coexists; old
  columns left alone. Migrate after Phase 1 lands and we're sure nothing
  reads the old columns.
- **`assigned_to_user_id` on todos and habits** — needed when chores are
  actually shared with family. Trivial follow-up migration.
- **Polymorphic `note_links` table** — currently `notes` has three nullable
  FKs (goal/todo/contact). When notes need to attach to recipes/events too,
  migrate to a polymorphic join table.
- **Row-Level Security (RLS) policies** — application-level enforcement
  is sufficient for now. Add RLS later as defense-in-depth.

---

## Schema state

The original schema (pre-Phase-0) is a snapshot at `app_schema.sql` (Brandon
has it on his Mac and on the NAS). Key entities:

**Hub-and-spoke around two hubs:**

- `goals` — hierarchical (`parent_id`), tracks progress (`target_value`,
  `current_value`, `unit`). Linked from todos, notes, habits, recipes,
  calendar_events.
- `todos` — hierarchical (`parent_id`), with `recurring` JSONB. Linked
  from calendar_events, habit_occurrences, grocery_lists, notes.

**Surrounding entities:**

- `calendar_events` — iCal-compatible (`ical_uid`, `rrule`, `exrule`)
- `contacts` + `contact_addresses` / `contact_emails` / `contact_phones`
  — vCard-compatible
- `habits` + `habit_occurrences` — habits define cadence; occurrences are
  materialized instances with status
- `notes` — typed (note/journal/idea/log/template), markdown content,
  attachable to goal/todo/contact via three nullable FKs
- `recipes` + `recipe_ingredients` + `recipe_steps`
- `grocery_lists` + `grocery_items` — items can reference `recipe_ingredients`

**Conventions across all tables:**

- UUID primary keys (`gen_random_uuid()`)
- `created_at` and `updated_at` timestamptz with `now()` defaults
- `update_updated_at()` trigger function exists; applied to mutable tables
- Cascading FKs for owned children, SET NULL for soft associations

**Phase 0 migration adds:**

- `households`, `users`, `household_memberships`, `refresh_tokens`
- `audit_log`, `attachments`
- `tags`, `taggings` (normalized; legacy `text[]` columns left alone)
- `schema_migrations` (version-tracking table)
- New enums: `actor_type`, `membership_role`
- Retrofits `household_id` (NOT NULL FK) and `created_by_user_id` (FK
  SET NULL) onto: `goals`, `todos`, `notes`, `calendar_events`, `contacts`,
  `habits`, `recipes`, `grocery_lists`
- Backfills a default household + a default `brandon@life-dashboard.local`
  user with sentinel password_hash `'!'` (cannot match argon2 — forces
  password setup on first backend run)
- Adds `updated_at` triggers to mutable tables that were missing them
- Adds `idx_*_household_id` indexes on retrofitted tables
- All wrapped in `BEGIN...COMMIT` (atomic)

**Note on child tables**: `contact_addresses`, `contact_emails`,
`contact_phones`, `grocery_items`, `recipe_ingredients`, `recipe_steps`,
`habit_occurrences` do NOT carry `household_id`. They inherit via parent
FK + cascading delete. This keeps the schema cleaner and simplifies inserts.

---

## Phase roadmap

| # | Phase | Status |
|---|---|---|
| 0 | Schema migration: users, households, audit, tags, attachments | **Drafted, NOT yet applied to NAS** |
| 1 | FastAPI backend scaffolding + auth + CRUD for all domains | Not started |
| 2 | Next.js frontend with auth + dashboard + CRUD pages | Not started |
| 3 | Local AI agent + MCP server + action vocabulary | Not started |
| 4 | Home Assistant integration (MQTT + custom component) | Future |

---

## Current status (as of latest session)

- Monorepo skeleton sits at `~/Code/Personal/life-dashboard/` on Brandon's Mac.
- Phase 0 migration files exist (`migrations/0001_*.up.sql` and `.down.sql`),
  syntax-validated by pglast (Postgres' real parser library), but **not yet
  applied** to the database on the NAS.
- Brandon has not yet transferred the monorepo to the NAS.
- There is an existing `life-dashboard/` folder on the NAS containing
  `API/`, `backups/`, `postgres/`, `ls_errors.txt`, `structure_detailed.txt`,
  `app_schema.sql`. The contents of `API/` and the text files are unknown to
  Claude — likely artifacts from a previous AI agent session ("Craft agents")
  that did the initial schema design. **Resolve this name collision before
  putting the new monorepo on the NAS.**

### The next concrete step

1. Have Brandon paste the output of `ls -la ~/life-dashboard/` and
   `cat ~/life-dashboard/structure_detailed.txt` so we know what's in the
   existing folder.
2. Decide where the new monorepo goes on the NAS (replace, rename old
   folder, or pick a different path).
3. Confirm `app_schema.sql` on the NAS still matches the schema the
   migration was drafted against (no schema drift during the week away).
4. Transfer the monorepo to the NAS (rsync or git — recommend `git init`
   on Mac first, push to a Gitea on the NAS, clone there).
5. Follow `docs/runbook.md` step-by-step: backup → copy migration into
   `postgres-1` container → dry-run → apply → verify.
6. Report verification output (orphan counts must all be zero).

Until Phase 0 lands successfully on the NAS, do not start Phase 1 work
— the backend's models will reflect against the post-migration schema.

---

## Repository layout

```
life-dashboard/
├── CLAUDE.md                    # This file
├── README.md                    # Project overview for humans
├── .gitignore
├── api/                         # FastAPI backend (Phase 1)
│   ├── src/life_dashboard/
│   │   ├── core/                # FastAPI-free service layer (extractable)
│   │   ├── domains/             # goals, todos, habits, ... one module each
│   │   ├── auth/                # argon2 + JWT + refresh tokens
│   │   ├── audit/               # middleware writing to audit_log
│   │   ├── events/              # In-process event bus, MQTT-ready
│   │   ├── mcp/                 # MCP server exposing core/ as LLM tools
│   │   └── api/                 # FastAPI routers — thin wrappers over core/
│   └── tests/
├── web/                         # Next.js frontend (Phase 2)
├── agent/                       # Local LLM agent client (Phase 3)
├── integrations/
│   └── home_assistant/          # Future HA custom integration (Phase 4)
├── infra/
│   ├── docker-compose.yml       # Fragment to merge into NAS compose
│   └── caddy/
├── migrations/                  # SQL migrations (Alembic-compatible later)
│   ├── 0001_multi_user_audit_tags_attachments.up.sql
│   └── 0001_multi_user_audit_tags_attachments.down.sql
└── docs/
    ├── architecture.md          # Long-form architecture
    ├── runbook.md               # Operational procedures (Phase 0+)
    └── agent-vocabulary.md      # Agent permission tiers + sample ops
```

The empty subdirectories under `api/src/life_dashboard/` are placeholders;
they get populated in Phase 1.

---

## Working style — how Brandon wants to work with Claude

These preferences emerged during the Phase 0 sessions. Honor them.

- **One deliverable per response, then stop and ask.** Don't run ahead of
  the user. After each material artifact, surface it for review and wait
  for explicit approval before the next.
- **Prefer prose explanations over bulleted lists** when explaining ideas.
  Lists are fine for genuine enumerations (file lists, command sequences,
  comparison tables); avoid them for narrative content.
- **Verify before handing off.** SQL goes through pglast. Code should be
  type-checked or test-run in the sandbox where feasible. Don't hand the
  user something that hasn't been validated to the level the sandbox allows.
- **Use the project folder, not a scratch directory.** Files belong at
  `~/Code/Personal/life-dashboard/` (mounted at
  `/sessions/happy-ecstatic-gates/mnt/Personal/life-dashboard/` in the
  sandbox), not in `outputs/`.
- **Don't try to reach the NAS.** This Claude session has no network path
  to the NAS. The user transfers files; the user (or Claude Code on the
  NAS) executes commands there. Generate artifacts and runbooks; let the
  user apply them.
- **Be opinionated.** When the user says "no preference," make the call
  and explain. Don't bounce decisions back.
- **Don't lecture about safety.** The user is technically literate and
  designing safety into his own system. Surface real risks; don't dwell.
- **Slash commands and skills**: this project uses default Claude Code
  conventions; no custom slash commands or skill packs are defined yet.

---

## Files generated so far (all under `~/Code/Personal/life-dashboard/`)

- `README.md`
- `CLAUDE.md` (this file)
- `.gitignore`
- `migrations/0001_multi_user_audit_tags_attachments.up.sql`
- `migrations/0001_multi_user_audit_tags_attachments.down.sql`
- `docs/architecture.md`
- `docs/runbook.md`
- `docs/agent-vocabulary.md`

Empty directories ready for future phases:
`api/src/life_dashboard/{core,domains,auth,audit,events,mcp,api}`,
`api/tests`, `web/`, `agent/`, `integrations/home_assistant/`,
`infra/caddy/`.

---

## Reference: where to find what

- **Architecture in depth** → `docs/architecture.md`
- **How to apply Phase 0 migration** → `docs/runbook.md`
- **Agent permission model and tiers** → `docs/agent-vocabulary.md`
- **The migration itself** → `migrations/0001_*.up.sql`
- **Original schema before any migrations** → Brandon's `app_schema.sql`
  (on his Mac and NAS; not stored in the repo because it's a snapshot of
  pre-existing state, not a migration)
