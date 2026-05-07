# Architecture

## Overview

`life-dashboard` is a household operating system — structured tooling for planning, tasks, habits, documents, routines, and life administration across a household. The core stack is:

- **Backend**: FastAPI (Python 3.12) with SQLAlchemy 2.x async and Alembic migrations
- **Frontend**: Next.js 15 (App Router) with Tailwind CSS v4 and shadcn/ui
- **Database**: Postgres (primary datastore; JSONB for flexible content fields)
- **Editor**: BlockNote, embedded in the frontend as the rich-text editing layer
- **AI layer**: planned augmentation layer; modular provider support (local LLM, BYOK, managed)

---

## Deployment Tiers

The product is designed around three tiers that share a common domain model and codebase.

### Single-machine self-hosted *(current)*

Docker Compose on a user-owned machine (e.g. a NAS or home server). One household, multiple accounts. No external dependencies beyond the host. This is the active deployment target today.

### Multi-machine self-hosted *(near future)*

Same Docker stack, accessible from multiple devices and household members. Sync is implicit via shared Postgres — no special sync layer required at this stage.

### Cloud-hosted / managed *(future, paid)*

Managed infrastructure with tiered pricing. The core product remains free and self-hostable; paid plans cover managed hosting, automated backups, mobile push, managed AI credits, and operational convenience. The open-core product must remain genuinely useful without the paid tier.

---

## Domain Model

### Primary entities

| Entity | Description |
|---|---|
| Household | Top-level shared container for all household data |
| Household member | A person represented in the household domain |
| Account | JWT-authenticated identity (email + password) |
| Role | Authorization level — owner, admin, member, viewer |
| Assignment | A task, chore, or responsibility linked to a household member |

### Product domains

The system provides structured support for:

- Tasks and todos (with household assignment and due dates)
- Recurring habits and completion tracking
- Goals and milestones
- Calendar events and scheduling
- Documents and pages (rich text via BlockNote, hierarchical page tree)
- Notes / Zettelkasten (planned — atomic notes, tags, wikilink backlinks)
- Recipes and meal planning
- Grocery and shopping lists
- Workouts and activity records
- Contacts and address book
- Tags (cross-domain polymorphic tagging)

---

## Data Scopes and Privacy

Privacy boundaries are modeled in code, not inferred from UI conventions.

| Scope | Visibility |
|---|---|
| Shared household data | All household members, subject to role rules |
| Personal data | Owning member only, unless explicitly shared |
| Sensitive data | Narrower visibility; extra caution in AI workflows |
| Administrative data | Billing, config, audit — restricted to owners/admins |

**Rules enforced at the service layer:**
1. Personal data is never included in shared household outputs without an explicit share action.
2. Scope filters are applied in backend service code, not only in frontend conditionals.
3. AI workflows that aggregate across scopes must respect the narrowest applicable visibility.

---

## Backend Structure

```
api/src/life_dashboard/
├── core/
│   ├── database.py       # Async engine, session dependency
│   └── settings.py       # Pydantic-settings config
├── auth/
│   ├── dependencies.py   # get_current_user — attaches household_id
│   ├── hashing.py        # argon2
│   ├── models.py
│   ├── router.py
│   ├── schemas.py
│   ├── service.py        # Bootstrap logic, token management
│   └── tokens.py
└── domains/
    ├── calendar_events/
    ├── contacts/
    ├── documents/        # BlockNote page tree (source_markdown + editor_json JSONB)
    ├── goals/
    ├── grocery_lists/
    ├── habits/
    ├── recipes/
    ├── tags/
    ├── todos/
    └── workouts/         # Strength, cardio, HIIT; polymorphic metrics JSONB
```

### Service layer discipline

Each domain follows `models → schemas → service → router`. The service layer (`*/service.py`) imports nothing from FastAPI — only SQLAlchemy and domain types. Both HTTP routers and the future AI agent call into the same service layer, keeping domain logic reusable and independently testable.

### Key patterns

- **`lazy="noload"` on all ORM relationships** — prevents `MissingGreenlet` errors in async context. Related data is loaded via explicit bulk queries, not relationship traversal.
- **True PATCH semantics** — `data.model_fields_set` distinguishes "field not sent" from "field sent as null". Only explicitly included fields are updated.
- **`household_id` on every domain entity** — every root table carries `household_id` and `created_by_user_id`. The auth dependency attaches `household_id` so routers never query the membership table directly.
- **JSONB for flexible content** — `editor_json` stores BlockNote's block tree; `source_markdown` stores original import markdown for lazy first-open conversion.

### Auth

argon2 password hashing, JWT access tokens (15-minute lifetime), httpOnly refresh token cookies with rotation. First-run bootstrap: a default user is seeded with a sentinel password hash that cannot be matched; on first startup, `BOOTSTRAP_PASSWORD` from the environment is hashed and written, then cleared.

---

## Frontend Structure

```
web/src/
├── app/
│   ├── (auth)/login/         # Login page
│   ├── (protected)/          # All authenticated routes; wrapped by Shell
│   │   ├── documents/        # Page tree sidebar + BlockNote editor
│   │   ├── todos/
│   │   ├── habits/
│   │   ├── goals/
│   │   ├── recipes/
│   │   ├── grocery-lists/
│   │   ├── workouts/
│   │   ├── contacts/
│   │   ├── calendar/
│   │   └── settings/         # Theme, sidebar, account settings
│   └── api/                  # Next.js route handlers proxying to FastAPI
├── components/
│   ├── shell/                # Sidebar nav, mobile header, command palette
│   ├── documents/            # Page tree, BlockNote editor, import dialog
│   ├── ui/                   # shadcn/ui primitives
│   └── [domain]/             # Domain-specific components
└── lib/
    ├── api/                  # openapi-fetch client, React Query wrapper, generated types
    ├── auth/                 # AuthContext, in-memory token management
    ├── theme/                # Palette presets, ThemeCustomizerContext
    ├── hooks/                # use-resizable-panel, etc.
    └── sidebar/              # SidebarConfigContext
```

---

## Database Schema

Alembic manages all schema evolution. Migrations live in `migrations/versions/`.

### Conventions

- UUID primary keys (`gen_random_uuid()`)
- `created_at` / `updated_at` timestamptz on every table; `updated_at` maintained by DB trigger
- `household_id` on all root entities; child tables inherit via parent FK
- Soft deletes via `archived_at` where recovery matters; hard deletes for dev/test resets only

### Current tables

| Table | Purpose |
|---|---|
| `households` | Top-level household container |
| `users` | Authenticated identities |
| `household_memberships` | User ↔ household join with role |
| `refresh_tokens` | JWT refresh token store |
| `documents` | Page tree (source_markdown + editor_json JSONB, parent_id hierarchy) |
| `todos` | Tasks with status, due date, recurrence JSONB, hierarchy |
| `habits` + `habit_occurrences` | Habit definitions and completion log |
| `goals` | Hierarchical goals with progress tracking |
| `recipes` + `recipe_ingredients` + `recipe_steps` | Recipe store |
| `grocery_lists` + `grocery_items` | Shopping lists |
| `workouts` + `exercise_entries` | Workout log; exercise metrics in JSONB |
| `contacts` + child tables | Contact store |
| `calendar_events` | Events with recurrence |
| `tags` + `taggings` | Polymorphic cross-domain tag system |

---

## Open-Core Boundary

| Layer | Open core | Premium / hosted |
|---|---|---|
| Household domain model | ✓ | |
| All domain features (tasks, habits, docs, recipes, etc.) | ✓ | |
| Self-hosted deployment | ✓ | |
| Basic AI / BYOK hooks | ✓ | |
| Managed hosting infrastructure | | ✓ |
| Automated backups | | ✓ |
| Polished mobile apps with push | | ✓ |
| Managed AI credits | | ✓ |
| Premium integrations (operational cost) | | ✓ |

The open core must be genuinely useful — not artificially limited. If a design makes the self-hosted product feel fake, push back.

---

## AI Layer (Planned)

The AI layer is an augmentation layer, not a source of truth.

- The LLM never reads the database directly and never writes outside controlled tool boundaries.
- AI tools are defined in `agent/` and call into the same backend service layer as the HTTP API.
- Provider integrations are modular: local LLM (Ollama/LM Studio), BYOK (OpenAI/Anthropic key), and future managed AI credits are all valid configurations.
- Destructive or bulk AI actions require human approval gates.
