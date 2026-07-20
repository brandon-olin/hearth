# Cowork "Instructions" blurb — Hearth

Paste the block below into the **Instructions** field of the Claude project used for
Hearth work. It orients a fresh remote session with no prior conversation history.

Keep it in sync when the repo layout or working agreements change.

---

## Blurb (copy from here down)

You are working on **Hearth**, a household operating system for planning, tasks, habits,
documents, routines, and life administration. Built open-core: the self-hosted path is
fully functional and free; managed cloud hosting is the paid tier.

**GitHub is the source of truth: https://github.com/brandon-olin/hearth**

Read from the repo rather than relying on memory or on anything I say in chat. If a
statement in conversation conflicts with what is in the repo, the repo wins — say so and
work from the repo. If you cannot reach the repo, tell me instead of guessing.

### Read these first, in this order

1. `CLAUDE.md` (root) — product vision, deployment model, domain concepts, cross-cutting
   principles, branch/merge protocol. This is the primary context document.
2. `claude-progress.txt` — append-only session log. **Read the last few `=== DATE ===`
   blocks** to learn what was just worked on and what the recommended next step is. Do not
   read the whole file; it is large.
3. `feature_list.json` — the feature ledger with `"passes"` flags and verification steps.
   Large; query it rather than reading it whole.
4. `ROADMAP.md` — longer-horizon direction.

### Then, scoped to the area of work

- `api/CLAUDE.md` — Python/FastAPI patterns, domain layout, JSONB conventions
- `web/CLAUDE.md` — Next.js patterns, UI primitive inventory, anti-patterns
- `infra/CLAUDE.md` — local install, Docker Compose, NAS deployment
- `plans/` — one numbered markdown file per work item; `plans/README.md` indexes them
- `plans/open-hearth.md` + `plans/open-hearth/` — the open-protocols / open-data /
  agent-access initiative (MCP server, exports, iCal feeds, Home Assistant, federation).
  Read this before touching any of those areas.
- `plans/marketing-site-spec.md` — gethearth.net (Next.js/Vercel, Stripe,
  household-as-customer billing)
- `docs/` — architecture, runbooks, install guides, writing tone, AI coach redesign

### Repository layout

```
api/         FastAPI backend — domain services, auth, Postgres via SQLAlchemy
web/         Next.js frontend — App Router, Tailwind, shadcn/ui, BlockNote
infra/       Docker Compose + Caddy config for self-hosted deployment
migrations/  Alembic schema migrations
agent/       AI automation and provider integrations
plans/       Per-feature design docs
docs/        Architecture, runbooks, setup guides
scripts/     Standalone utility scripts
```

### Working agreements that are easy to get wrong

- **Progress tracking is mandatory.** After any meaningful unit of work, append a new
  `=== DATE — session type ===` block to `claude-progress.txt` (never edit previous
  blocks) and flip `"passes": true` in `feature_list.json` for features whose every
  verification step now passes. Never remove or rename feature entries.
- **Do not edit `feature_list.json` or `claude-progress.txt` mid-build.** They are the top
  merge-conflict source. Update them in the final commit, after rebasing onto current main.
- **One feature per branch** (`feat/<feature-id>`). Merge protocol: rebase on
  `origin/main`, re-parent Alembic `down_revision` if main gained a migration, verify a
  single head with `alembic heads`, run the full gate (pytest + ruff, plus `tsc --noEmit`
  for web changes), then update the two tracking files, then merge locally.
- **Pushing `main` is mine, not yours.** `git push origin main` triggers a cloud build and
  an automatic Alembic migration against prod. Merge locally; I push.
- **Scripts use Python stdlib only** — `urllib.request`, never `requests` or `httpx`.
  Third-party HTTP libs fail unpredictably here due to interpreter path ambiguity.
- **No feature ships without its MCP verb.** The web UI and AI agents are peer clients of
  the same service layer. Any new user-facing capability exposes its agent-surface
  equivalent in the same build. Tool descriptions and error messages are agent UX.
- **Write idempotently.** Every POST/PATCH that mutates state must tolerate being called
  twice. State transitions (e.g. completing a recurring todo) must be atomic.
- **Smoke-test every new endpoint by actually executing it**, not just by confirming it
  registers. Import errors have shipped past registration checks before.
- Domain logic lives in service layers, not routers or UI components. All writes go
  through service functions.
- Privacy by default: shared / personal / sensitive data scopes are real boundaries. Data
  leaking across a scope boundary is a design bug, not a cosmetic one.

### Local dev commands

```
api:        cd api && source .venv/bin/activate && uvicorn life_dashboard.main:app --reload --port 1338
migrations: cd api && alembic upgrade head
web:        cd web && npm run dev
```

Current phase is **local / single-machine** (venv + npm + local Postgres, no Docker).
Next is self-hosted NAS via Docker; cloud-hosted with payments is later. Prefer designs
that work across all three tiers without a rewrite, and avoid infrastructure
disproportionate to the current phase.

### When unsure

Preserve privacy and data-scope boundaries; keep the design portable across the three
deployment tiers; prefer the simplest implementation that leaves future options open; ask
me when business-model or privacy implications are significant.
