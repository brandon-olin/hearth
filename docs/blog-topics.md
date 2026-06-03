# Hearth — Blog Post Topics

A running list of writing opportunities from the Hearth project. Goal: use each post as a learning exercise — review the code, ask questions, get taught the nitty-gritty, then write it down. Career self-promotion that actually builds knowledge.

**The throughline for the series:** "I designed a system that has to work the same way whether it runs on your laptop, a NAS, or Vercel — and that constraint forced real architectural discipline."

---

## Priority Posts

### 1. Multi-tenancy and Privacy-by-Design
**Why it signals:** This is the thinking that separates senior from mid-level. Most portfolio projects don't touch it.

**Core ideas to cover:**
- The `Household` as the top-level container — why everything is scoped to it
- The membership role hierarchy (`owner` / `admin` / `member` / `viewer`) and how it's derived at auth time rather than stored as a column
- Personal vs. shared vs. sensitive data scopes — how the choice was made intentionally, not as an afterthought
- The design principle: "data leaking across scope boundaries is a design bug"
- How household scoping is enforced in service functions, not routers — and why that matters

**Code to revisit:**
- `api/src/life_dashboard/auth/` — how `household_id` and `role` get attached at auth time
- `api/src/life_dashboard/households/router.py` — admin-gating with `_ADMIN_ROLES`
- Any domain service (e.g., todos, habits) — the `household_id` filter on every query

**Questions to ask / things to learn:**
- [ ] What happens if the household_id filter is accidentally omitted from a query?
- [ ] How would you test that a member from Household A can't read Household B's data?
- [ ] What does "role derived from membership join" actually look like in the auth dependency?

---

### 2. End-to-End Type Safety Without Writing Types
**Why it signals:** A real productivity unlock that lots of devs have heard of but haven't implemented. Maps to "API design" and "TypeScript" on any roadmap.

**Core ideas to cover:**
- The contract: Pydantic models in Python → FastAPI generates an OpenAPI schema → `openapi-typescript` generates `schema.d.ts`
- What you get: fully typed `$api.useQuery` and `$api.useMutation` calls, typed path params, typed request bodies, typed responses
- Zero manual type maintenance — change a Pydantic schema, regenerate, TypeScript tells you everywhere that breaks
- The `openapi-react-query` wrapper and why it's the right abstraction
- When it breaks down (JSONB fields typed as `dict[str, Any]` — the escape hatch)

**Code to revisit:**
- `api/src/life_dashboard/domains/*/schemas.py` — the `Create` / `Update` / `Response` pattern
- `web/src/lib/api/schema.d.ts` — what the generated output looks like
- `web/src/lib/api/query.ts` — the `$api` wrapper
- The `openapi-typescript` regeneration command in `web/CLAUDE.md`

**Questions to ask / things to learn:**
- [ ] Walk through a full round-trip: add a field to a Pydantic schema → regenerate → TypeScript error → fix
- [ ] Why `model_fields_set` matters for partial updates (PATCH semantics)
- [ ] What's the tradeoff of JSONB fields that are `dict[str, Any]`?

---

### 3. Auth That Handles the Real Stuff
**Why it signals:** Most "I built auth" posts describe the happy path. This one has the tricky parts.

**Core ideas to cover:**
- Why access tokens live in memory (not localStorage) — XSS and the security tradeoff
- Silent refresh — how the frontend re-acquires a token without interrupting the user
- Role-based access derived from the membership join (no `role` column on `users`)
- Rate limiting on auth endpoints — brute force protection with `slowapi`, 429 + Retry-After
- Dev impersonation — why it's useful, how it's gated to non-production, and how the frontend handles the amber banner

**Code to revisit:**
- `web/src/lib/auth/token.ts` — in-memory token store
- `web/src/lib/auth/context.tsx` — the full `AuthContextValue` interface, silent refresh, impersonation
- `api/src/life_dashboard/auth/` — JWT creation, hashing, session management
- `api/src/life_dashboard/households/router.py` — the impersonation endpoint and its environment guard
- Rate limiting setup in `main.py` or wherever `slowapi` is wired in

**Questions to ask / things to learn:**
- [ ] What's the actual XSS risk with localStorage tokens vs. memory tokens?
- [ ] How does silent refresh work without a refresh token in a cookie?
- [ ] What does the `_ADMIN_ROLES` guard look like and why is it a set at the module level?

---

### 4. Idempotency — Both Sides of the Stack
**Why it signals:** Almost nobody writes about this clearly. Shows you've been burned by the real-world failure modes. Senior-level thinking.

**Core ideas to cover:**
- Why idempotency matters in a household app: network retries, mobile double-taps, background refetches
- The race condition in recurring todo completion — two concurrent requests both seeing `completed_at IS NULL`
- `SELECT … FOR UPDATE` — what it does, why the gap between check and insert is dangerous without it
- `UPDATE WHERE completed_at IS NULL RETURNING id` — the cleaner alternative for status flips
- The frontend's half of the contract: disabling submit during `isPending`, idempotency keys tied to form-open time (not submit time)
- The `UniqueConstraint` / `IntegrityError` pattern for association tables

**Code to revisit:**
- `api/CLAUDE.md` — the Idempotency section (Patterns A, B, C)
- `api/src/life_dashboard/domains/todos/service.py` — `update_todo` and the recurring completion path
- `api/src/life_dashboard/domains/habits/service.py` — occurrence completion
- `web/CLAUDE.md` — the "Idempotency — the frontend's half" section
- Tags / taggings domain — example of `UniqueConstraint` + get-or-create

**Questions to ask / things to learn:**
- [ ] Show me the race condition step by step — what would actually happen without the FOR UPDATE?
- [ ] Why does swallowing an IntegrityError without rolling back break SQLAlchemy's session?
- [ ] When is optimistic UI safe vs. dangerous? (status flips OK, new entity creation not)

---

### 5. AI Integration Patterns Beyond "I Called the API"
**Why it signals:** Hot market, and the implementation here is more thoughtful than most. CBT framing, multi-layer context, tool use.

**Core ideas to cover:**
- The three-layer context model: user profile + journal narrative signals + raw recent entries
- Why the profile is silently maintained (auto-bootstrap on key save, incremental updates from journaling) rather than user-facing
- The `update_profile` chat tool — AI calls it silently when the user expresses something durable; it doesn't mention the tool
- Context-aware chatbot: knowing which resource the user is looking at without them pasting content
- Journal signal extraction: sentiment, self-talk valence, themes — extracted async, never blocking the note save
- The CBT method prompt: reality-testing harsh self-talk against behavioral data, honest during real dips, no manufactured lessons

**Code to revisit:**
- `api/src/life_dashboard/domains/` — the AI coach and chat domains
- `docs/ai-coach-redesign.md` — the full design document
- The `_fetch_narrative_context` helper
- The `chat_context_resolver` dispatch logic

**Questions to ask / things to learn:**
- [ ] How is the profile injected into the system prompt without the user knowing?
- [ ] What makes the `update_profile` tool call "silent" from the user's perspective?
- [ ] How do you prevent the journal signal extraction from blocking a note save if the AI provider is down?
- [ ] What's the difference between a CBT "reality test" and just being positive?

---

### 6. One Codebase, Three Deployment Targets
**Why it signals:** Shows system-level thinking. The constraint forced real architectural decisions, not just "works on my machine."

**Core ideas to cover:**
- The three tiers: local (no Docker), self-hosted NAS (Docker Compose + Tailscale), cloud (Vercel + Railway + Neon)
- The Next.js API proxy — `API_URL` in `.env.local` is the only thing that changes between local and NAS
- The Tauri problem: static export with no Next.js server, `useSegmentId` replacing `useParams`, `TauriRscPatch` for RSC payloads
- `apiBaseUrl` and `resolveMediaUrl` — why hardcoding `/api/` would break the desktop app
- How the same FastAPI codebase runs under uvicorn locally, Docker on a NAS, and Railway in the cloud
- Launchd on macOS for always-on local service with port split (1338 vs. 1339)

**Code to revisit:**
- `web/CLAUDE.md` — the Tauri static export section
- `web/src/lib/hooks/use-segment-id.ts`
- `web/src/components/tauri-rsc-patch.tsx`
- `web/src/lib/api/client.ts` — `apiBaseUrl` and `resolveMediaUrl`
- `infra/` — Docker Compose and Caddy config
- `infra/CLAUDE.md` — launchd setup

**Questions to ask / things to learn:**
- [ ] Walk me through exactly what goes wrong when you use `useParams()` in a Tauri static export
- [ ] What does `TauriRscPatch` intercept and why can't it touch API calls?
- [ ] How does the port split (1338/1339) work with launchd?

---

## Bonus / Future Posts

**Budget system as a data modeling challenge**
The budget profiles model (Personal / Household / Business), zero-based envelope budgeting, category groups, rollover, income forecasting, and cross-profile transaction re-attribution. Good for a "data modeling real financial workflows" angle.

**The meta post: Building a production app with AI coding tools**
What the agent was good at, where it made architectural mistakes you caught, what required genuine engineering judgment. The `claude-progress.txt` and `feature_list.json` are receipts. This is the post that gets shared right now.

**Async SQLAlchemy patterns**
The four-file domain pattern, `AsyncSession` and why it's different from sync SQLAlchemy, preventing N+1 queries by batch-loading (see the habits `list_habits` implementation), JSONB for flexible schemas without migrations, the `_as_aware()` timezone normalization helper.

---

## Writing Process Notes

Each post = review code here → ask questions → get taught the nitty-gritty → write it up.

The goal isn't to document what was built — it's to demonstrate that the concepts are understood. Write in first person. Show the mistake or the constraint that forced the decision. Don't start with "In this post I will cover."
