# Architecture

## Principles

1. **Local-first.** Every piece of household data lives on hardware
   Brandon owns. No third-party cloud sees the contents of this
   database. Remote access is via Tailscale, not the public internet.
2. **Governed AI.** The LLM never speaks SQL. It interacts with the
   data through a fixed vocabulary of backend operations that validate,
   authorize, and audit every write.
3. **Extensible.** New domains (garden, orchard, home projects, travel)
   are added as modules in the backend's `domains/` directory. The
   action vocabulary grows with them.
4. **Interop-friendly.** The data model speaks standard formats:
   iCal-compatible calendar, vCard-compatible contacts, markdown for
   notes. This keeps door open to Home Assistant integration, CalDAV/
   CardDAV sync, or porting pieces elsewhere.

## Components

### Database (NAS, existing)
Postgres 16 in the `postgres-1` container, database `life_dashboard`,
owner `brandon`. Phase-0 migration adds users, households, audit, tags,
attachments and retrofits ownership on existing entities.

### Backend (NAS, Phase 1)
FastAPI + SQLAlchemy 2.0 async + Alembic. Deployed as a Docker container
on the same internal network as `postgres-1`. Talks to the DB over the
container network — the DB is never exposed to the LAN.

Internal structure:

```
api/src/life_dashboard/
├── core/      # Pure service layer, no FastAPI. Business logic lives here.
├── domains/   # One module per domain (goals, todos, habits, ...)
├── auth/      # argon2 password hashing, JWT, refresh tokens
├── audit/     # Middleware + repository writing every write to audit_log
├── events/    # In-process event bus; MQTT emitter added in Phase 4
├── mcp/       # MCP server wrapping core/ as tools for the LLM
└── api/       # FastAPI routers — thin HTTP wrappers over core/
```

The `core/` layer imports nothing from `api/` or `mcp/`. Routers and
MCP tools both call into `core/`. This is the seam that makes the
service layer extractable as an HA custom integration later.

### Frontend (NAS, Phase 2)
Next.js App Router on the same docker-compose network as the backend.
Server Components fetch from the backend using a typed OpenAPI client
generated at build time. Writes go through TanStack Query mutations.

### Local agent (gaming PC, Phase 3)
A small Python program that:
- Discovers the backend's MCP server (URL configured via env).
- Runs a local LLM (llama.cpp / Ollama / LM Studio).
- Takes user prompts, plans actions, calls MCP tools.
- Respects the permission model: read freely, write with audit,
  destructive/bulk ops emit approval requests that surface in the UI.

### Home Assistant integration (future, Phase 4)
MQTT emitter in the backend's `events/` module publishes topics like
`life_dashboard/todos/created`. A custom HA integration (Python) listens,
exposes entities, and can trigger automations. Bidirectional: HA
automations can call backend endpoints to create tasks / log events.

## Network topology

```
[ Family phones / laptops ]
           |
           | Tailscale
           |
[ NAS ] ------ docker network ------+
  |                                  |
  |-- life-dashboard-web (Next.js)  |
  |-- life-dashboard-api (FastAPI) -+
  |-- postgres-1 ---------------- -+
  |-- caddy (TLS terminator)

[ Gaming PC ] --Tailscale--> [ life-dashboard-api MCP endpoint ]
  |
  |-- local LLM (llama.cpp / Ollama)
  |-- agent/ (Python)
```

## Permission model (sketch)

Three actor types: `user`, `agent`, `system`.

- **user**: authenticated human with a household membership.
  Role determines what they can do (owner/admin/member/viewer/agent).
- **agent**: the local LLM, identified by an agent user record
  (`is_agent = true`). Scoped by what's allowed in its permissions.
- **system**: automated jobs, migrations, imports.

Every write through the backend:
1. Authenticates the actor and resolves their household.
2. Validates the payload.
3. Checks authorization (can this actor do this op in this household?).
4. Executes in a transaction.
5. Writes an `audit_log` row with a structured `diff`.
6. Emits an event to the in-process bus.

Destructive or bulk operations (delete-many, update-many, bulk import)
require a higher role and/or return a "proposed change" that must be
approved by a user before execution.

## Data integrity notes

- Child tables (contact_addresses, grocery_items, recipe_ingredients,
  recipe_steps, habit_occurrences) do not carry `household_id` — they
  inherit from their parent and cascade on parent delete.
- The `notes` table has three parallel nullable FK columns
  (`goal_id`, `todo_id`, `contact_id`). If we need notes on more entity
  types, we'll migrate to a polymorphic `note_links` table rather than
  adding more columns.
- Tags exist in two places: legacy `text[]` on `notes.tags` and
  `recipes.tags`, plus the new normalized `tags` + `taggings` tables.
  The migration does not touch the legacy columns. Phase 2 or later
  will migrate legacy tags into the normalized form and drop the old
  columns.
