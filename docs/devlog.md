# life_dashboard — Developer Log

A running record of progress, decisions, and context for the life_dashboard project — written as it happens, so the full picture is never lost.

---

## What We're Building

life_dashboard is a local-first life-management system for a household. The core idea: all personal data — tasks, goals, calendar, notes, recipes, contacts, habits, grocery lists — lives in a self-hosted Postgres database on a home NAS, never leaving the hardware. A FastAPI backend exposes that data through a clean API. A Next.js web app is the day-to-day interface for the family. And eventually, a local LLM running on a home gaming PC acts as an AI assistant that can reason over the data and take actions — without ever being given raw database access.

This is a privacy-first, household-scale system. Not a SaaS product, not a Home Assistant plugin, not a replacement for any single app — it's a platform that ties all of those things together on hardware you own.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Database | Postgres 16 (existing, self-hosted in Docker on Synology NAS) |
| Backend language | Python 3.12 |
| Backend framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Auth | argon2 + JWT + refresh tokens |
| Frontend | Next.js (App Router) |
| Frontend styling | Tailwind + shadcn/ui |
| Frontend data | TanStack Query + OpenAPI-typed client |
| Deployment | docker-compose on the NAS |
| Remote access | Tailscale (no public internet exposure) |
| AI agent | Local LLM (Ollama / LM Studio) + MCP server |

---

## Roadmap

| Phase | Description | Status |
|---|---|---|
| 0 | Schema migration: multi-user, audit log, tags, attachments | ✅ Complete |
| 1 | FastAPI backend: auth, CRUD for all domains, MCP server | 🔜 Next |
| 2 | Next.js frontend: auth, dashboard, CRUD pages | Not started |
| 3 | Local AI agent + action vocabulary | Not started |
| 4 | Home Assistant integration | Future |

**Current position: Phase 1 is complete. Starting Phase 2.**

---

## Design Considerations

- **Privacy-first, hardware-owned.** All data lives on the NAS. Remote access is via Tailscale — a personal VPN — not the public internet. Nothing touches a cloud service.

- **Governed AI.** The local LLM agent never speaks SQL. It operates through a fixed vocabulary of structured operations (create a todo, summarize my week, suggest a recipe) with input validation, audit trails, and human approval gates for anything destructive. The AI is powerful but legible.

- **Composable for open source.** The backend's service layer is deliberately decoupled from FastAPI — it lives in `core/` and imports nothing from the HTTP layer. Both the REST API and the MCP server call into the same `core/`. This means the service layer can be extracted, reused, or contributed to as a standalone library.

- **Home Assistant integration path.** Home Assistant is written in Python. By keeping the backend's service layer as pure Python with no framework dependencies, it's a natural candidate to be wrapped as an HA custom integration later — giving the dashboard access to presence detection, sensor states, and device control without building a separate bridge.

- **Multi-user from day one.** Every core entity in the database carries `household_id` and `created_by_user_id`. It's a single-household system (not multi-tenant SaaS), but it's designed for multiple humans in that household. Adding family members later requires no schema changes.

- **Open format interop.** Calendar events are iCal-compatible. Contacts are vCard-compatible. Notes are markdown. This keeps doors open: a future CalDAV/CardDAV sync, an HA calendar widget, or a mobile calendar app could all consume the data without lock-in.

- **Audit everything.** Every write through the backend produces an `audit_log` row with a structured diff and the actor's identity. This matters especially once the AI agent is in the loop — you can always see what it did and why.

---

## Progress Log

### Phase 0 — Schema Migration (Complete)

**What the existing schema looked like:** The Postgres database already had a solid domain schema — goals, todos, habits, notes, calendar events, contacts, recipes, grocery lists. All with UUIDs, timestamps, and sensible relationships. But it had been designed for a single user with no concept of households, no audit trail, and no structured tags.

**What Phase 0 added:**

- `households` and `users` tables with `household_memberships` joining them. Every core entity was retrofitted with `household_id` (NOT NULL) and `created_by_user_id`.
- An `audit_log` table that will record every backend write with actor identity and a structured diff.
- An `attachments` table for file references linked to any entity.
- A normalized `tags` + `taggings` system, coexisting with legacy `text[]` tag columns (those get migrated later once the backend is confirmed stable).
- `refresh_tokens` for the JWT auth system.
- A `schema_migrations` version-tracking table.
- Backfill of a default household and a sentinel `brandon@life-dashboard.local` user (password hash `'!'` — cryptographically impossible to match, forces password setup on first backend run).
- Missing `updated_at` triggers added to tables that lacked them.
- Household-scoped indexes on every retrofitted table.

**How it was applied:**

The migration SQL was written by hand and validated with `pglast` (Postgres's real parser library) before touching the database. A schema-only backup was taken via `pg_dump` into the `backups/` folder. The migration was copied into the running `postgres-1` container and applied with `psql`. Post-migration, orphan counts on all eight retrofitted tables returned zero — confirming the backfill was clean.

**Infrastructure work to get there:**

Getting the monorepo from the development Mac to the NAS required a few detours: `git` isn't installed on Synology DSM by default, rsync over SSH was blocked by DSM's SSH configuration, and the destination directory needed to exist before transfer. The eventual solution was piping `tar` through SSH — a reliable fallback that bypasses rsync's server-mode requirement entirely.

### Phase 1 — FastAPI Backend (Complete)

Phase 1 was the largest single chunk of work in the project so far — going from a database with no application layer to a fully deployed, smoke-tested REST API running in Docker on the NAS.

**What was built:**

The backend covers every domain in the schema. Auth landed first — argon2 password hashing, JWT access tokens (15-minute lifetime), httpOnly refresh token cookies, and a first-run bootstrap flow that lets you set a real password for the sentinel user created in Phase 0. From there, ten domain modules were built in sequence: tags, notes, goals, todos, habits, calendar events, contacts, recipes, and grocery lists. Each follows a strict four-file structure (models → schemas → service → router) with all database logic isolated in the service layer and thin FastAPI wrappers in the router.

Two additional Alembic migrations were written and applied to the live NAS database during this phase: one dropping the legacy `text[]` tags column from notes (replaced by the normalized `taggings` table), and one adding Obsidian-style hierarchy (`parent_note_id`) and a graph links table (`note_links`) to notes.

The notes domain became the reference implementation — it's the most complex, handling hierarchical structure, graph links, backlinks, and polymorphic tags all loaded via bulk queries in four round trips. Every other domain that came after it was modeled on the same patterns.

**The hard-won lessons:**

Several of these bit during development and are worth understanding because they'll surface again in Phase 2 and beyond.

The async SQLAlchemy constraint that caused the most friction was `lazy="noload"` on relationships. In an async context, SQLAlchemy raises `MissingGreenlet` the moment you touch a relationship attribute that hasn't been explicitly loaded — including when Pydantic calls `model_validate()` on an ORM object. The fix is to declare every relationship as `lazy="noload"` and load related data manually via bulk queries before building the response. The `_enrich()` pattern in the notes service is the canonical example: load the main objects, then fetch tags, children, links, and backlinks in separate `SELECT ... WHERE id IN (...)` queries, then inject them via `model_copy()`.

SQLAlchemy's enum handling against an existing Postgres schema has a silent footgun: if you pass the type name as a string to `SaEnum()` instead of the actual enum values, it creates a single-member enum containing the type name as a literal value. Everything appears to work until runtime, when SQLAlchemy tries to map a real value like `"medium"` to a Python object and raises `LookupError`. The fix: always pass the actual string values (or the Python enum class) to `SaEnum`, and always set `create_type=False` since the types were created by migrations, not the ORM.

Pydantic-settings has a similar silent failure with list fields. If you declare `allowed_origins: list[str]`, pydantic-settings tries `json.loads()` on the env var value before any validator runs. A bare comma-separated string isn't valid JSON, so it raises `ValidationError` at startup with a confusing message. The fix is to declare it as `str` and split it at point of use in `main.py`.

The `metadata` naming collision was a one-time surprise: SQLAlchemy's `DeclarativeBase` reserves the class attribute name `metadata` for its own use. Any ORM column named `metadata` has to be aliased to `metadata_` in Python and mapped back with `mapped_column("metadata", ...)`. The Pydantic response schema then uses `validation_alias="metadata_"` to serialize it correctly.

**Deployment stumbling blocks:**

Getting the backend running on the NAS surfaced a set of Synology-specific quirks that are now documented in CLAUDE.md so they don't need to be rediscovered.

The Docker network was the trickiest: the `postgres-1` container lives on a manually-created Docker network (`docker network create life-dashboard`). Docker Compose refuses to adopt a manually-created network unless you declare it `external: true` in the compose file — without that flag it tries to create its own network with the same name, fails because it already exists, and errors out with a confusing message.

Alembic's migration files and `alembic.ini` are not part of the installed Python package — they're plain files on disk. The Dockerfile initially only copied `src/`. Running migrations inside the container failed immediately with `No 'script_location' key found in configuration` until those two explicit `COPY` directives were added to the runtime stage.

`docker compose run --rm` does not rebuild the image. This seems obvious in retrospect, but after updating the Dockerfile and re-running the migration command, the old cached image kept running. Explicit `docker compose build api` is required any time the Dockerfile changes.

One last one that caused twenty minutes of confusion: `GID` is a read-only special variable in zsh. Using it as a shell variable to store a grocery list ID during smoke testing raises `bad math expression: operand expected` with no useful context about why. Use any other name.

---

## Forward-Looking Architecture Decisions

**Python + FastAPI** is the right choice beyond just being familiar. Python has the richest LLM and AI agent ecosystem — LangChain, LlamaIndex, the official Anthropic and OpenAI SDKs, and the MCP SDK all speak Python natively. Home Assistant is also Python, meaning the service layer can eventually be wrapped as a custom integration with minimal friction.

**The service layer split** (`core/` vs `api/`) is the most consequential architectural decision in the project. By keeping all business logic in a FastAPI-free layer, three consumers can share it without duplication: the HTTP REST API, the MCP server (which the local LLM calls), and any future HA integration. This also makes the service layer independently testable.

**MCP (Model Context Protocol)** is the bridge between the local LLM and the backend. Instead of giving the AI a database connection and hoping for the best, the MCP server exposes a curated set of typed tools — "create a todo," "list habits due this week," "log a habit occurrence." The LLM calls tools; it never writes SQL. This is what makes the AI assistant safe to run on household data.

**Async SQLAlchemy** is more setup than the sync version but pays off when the AI agent is making multiple concurrent reads (summarizing goals while fetching upcoming calendar events while checking habit streaks). It also positions the backend well if a mobile app or real-time frontend feature ever needs WebSocket support.

**Tailscale over a public server** means there's no attack surface to maintain, no TLS certificate management beyond a single Caddy config, and no monthly VPS bill. The family accesses the dashboard by URL on their phones, exactly like any web app — they just happen to be on a private network.
