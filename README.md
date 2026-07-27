# Hearth

**A privacy-first "household operating system" — a full multi-tenant SaaS, built and shipped solo.**

Hearth is one app for a family or shared household to run planning, tasks, chores, habits, documents, recipes, meal planning, grocery lists, budgeting with bank sync, workouts, calendar, contacts, notes, and an AI life-coach — with hard privacy boundaries between *shared*, *personal*, and *sensitive* data.

It runs from a single codebase across three tiers — **local (no Docker), self-hosted (NAS/Docker), and managed cloud** — where one `DEPLOYMENT_TIER` setting changes egress policy, credential sourcing, and feature availability without a rewrite.

<!-- HERO SCREENSHOT — drop the marketing-page hero shot/GIF of the dashboard here:
     ![Hearth dashboard](docs/screenshot-dashboard.png)
     This is the highest-leverage element in the README — a visitor sees the product works
     before doing anything. Reuse the same asset produced for the marketing site. -->

**▶️ Walkthrough:** <!-- paste the 60–90s Loom link here once recorded (dual-use with the marketing page) -->

---

## By the numbers

| | |
|---|---|
| Backend | ~46,500 lines of async Python — **256 REST endpoints**, **18 product domains** |
| Frontend | ~65,000 lines of TypeScript/React |
| Tests | **543** test functions across 39 files (pytest, async) |
| Migrations | **54** Alembic migrations, portable across Postgres **and** SQLite |
| AI surface | **~24 MCP tools** exposed to AI agents |
| Built by | One person, ~3 months |

## Stack

**Backend:** Python 3.12 · FastAPI · SQLAlchemy 2.x (async) · Alembic · PostgreSQL / SQLite · Pydantic v2
**Frontend:** Next.js 16 · React 19 · TypeScript · Tailwind v4 · shadcn/ui · TanStack Query (typed client generated from the API's OpenAPI schema)
**Desktop:** Tauri 2 (Rust shell)
**AI:** Anthropic Claude API · Model Context Protocol (MCP) · prompt caching
**Infra:** Docker · Caddy · Tailscale · Vercel · Railway · Neon

---

## What makes it more than a CRUD app

- **Multi-tenant privacy by design.** One visibility rule (shared / personal / sensitive), expressed as a matched pair that must agree: `apply_visibility_filter` pushes it into SQL so the database never returns rows a user can't see, and its mirror `can_see` filters in-memory events (SSE stream, outbound webhooks, agent proposals) where there's no query to attach it to. Cross-scope leakage is treated as a bug — and a real cross-tenant write defect was found and fixed.
- **Correctness under concurrency.** Idempotent writes, atomic recurring-task completion (row locks + SAVEPOINTs), DB-level import dedup via partial unique indexes, double-submit guards on financial writes.
- **Security-grade auth, from scratch.** OAuth 2.1 authorization server, scoped personal-access tokens with rate limiting, argon2 + JWT sessions, RBAC, and Fernet field-level encryption with documented key rotation.
- **AI agents as first-class clients.** An in-process MCP server exposes ~24 tools plus an **agent-proposal/approval system** — agents act under the *same* permission and data-scope rules as humans, with an audit hook. Prompt caching cut chat inference cost **2.2–2.9×** after profiling that tool schemas alone shipped ~15.6k tokens per call.
- **Tier-aware SSRF defense** on outbound webhooks (blocks private/loopback targets and DNS-rebinding on cloud; intentionally allows LAN targets when self-hosted, so it can drive Home Assistant).
- **Built by its own AI pipeline.** A Telegram-triggered Claude Code agent harness with a machine-readable feature backlog, one-feature-per-git-worktree isolation, and a serialized rebase/merge protocol — the system that built the product.

---

## Architecture

```
api/          FastAPI backend — domain services, auth, async Postgres/SQLite
web/          Next.js frontend — App Router, typed OpenAPI client
desktop/      Tauri 2 desktop shell (Rust + web build)
agent/        AI automation / autonomous coding-agent prompts
infra/        Docker Compose, Caddy, Tailscale, launchd/systemd, Telegram bot
migrations/   54 Alembic migrations (Postgres + SQLite)
plans/        Architecture Decision Records & hardening plans
docs/         Product, architecture, and operational docs
```

**Design discipline enforced throughout:** all business logic lives in domain service layers (never in routers or UI); the app is typed end-to-end (Pydantic v2 → OpenAPI → generated TS types); and **no feature ships without its MCP verb** — the web UI and AI agents are peer clients of the same service layer.

---

## Deployment tiers

| Mode | Use case | Storage | Sync |
|---|---|---|---|
| Local-only | One household, one machine — no Docker | On-device DB (SQLite) | No |
| Self-hosted | Technical households, shared access | Your infra (Docker + Postgres, Caddy TLS, Tailscale) | Yes |
| Managed cloud | Non-technical households | Vercel + Railway + Neon | Yes |

Open-core (AGPL-3.0): the self-hosted product is fully functional and free forever; the paid tier ($8/mo) sells managed *operations*, not feature gates. Cost-bearing features (AI, bank sync) run bring-your-own-key when self-hosted. Subscription/tier tracking is schema-ready (Stripe integration planned) — the cloud tier is deployed and running; metered billing is in progress.

---

## License

AGPL-3.0. Anyone can use, modify, self-host, and share Hearth — including commercially — with one requirement: run a modified version as a network service and you must make your source available to its users. Self-hosting households are unaffected. Snapshots prior to 2026-07-17 remain MIT-licensed.
