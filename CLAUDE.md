# CLAUDE.md — life-dashboard

Root context for the `life-dashboard` monorepo. Each subdirectory has its own `CLAUDE.md` with implementation-level detail. Keep this file focused on product vision, deployment model, and cross-cutting principles.

---

## What this is

**Hearth** is a household operating system for planning, tasks, habits, documents, routines, and life administration. It is designed for real households — meaning multiple people sharing data, with clear privacy boundaries between personal and shared content.

The product is built open-core: the core app and self-hosted path are fully functional and free; cloud hosting with managed infrastructure is the premium tier.

---

## Deployment model

Three tiers, in order of implementation priority:

1. **Local / single-machine** *(active focus)*
   FastAPI + Next.js + Postgres running directly on the developer's machine (venv + `npm run dev` + local Postgres). No Docker required for this phase. Goal: get the product polished and feature-complete before moving to hosted deployment.

2. **Self-hosted (NAS / Docker)** *(next)*
   Same stack packaged as Docker Compose, running on a user-owned machine (e.g. Synology NAS) behind Tailscale + Caddy TLS. One household, multiple accounts.

3. **Cloud-hosted / managed** *(future, paid)*
   Deployed to Vercel (web) + managed Postgres, with payment processing. Tiered pricing: free self-hosted forever; paid for managed hosting, backups, mobile push, managed AI credits.

**Current dev workflow:** run API locally with `cd api && source .venv/bin/activate && uvicorn life_dashboard.main:app --reload --port 1338`. Run migrations with `alembic upgrade head` from the same `api/` directory. Run web with `cd web && npm run dev`.

When making design decisions, prefer the approach that works across all three tiers without requiring a rewrite.

---

## Core domain concepts

- **Household** — top-level container; all data is scoped to a household.
- **Member** — a person within a household; has their own account.
- **Account** — an authenticated identity (JWT-based; email + password today).
- **Assignment** — a task, chore, or responsibility attached to a member.
- **Data scope** — shared (visible to all household members), personal (one member), or sensitive (admin only).

Do not reduce the architecture to "single-user app + notes". Model real household workflows even when early releases only support one household per install.

---

## Repository layout

```
api/        FastAPI backend — domain services, auth, Postgres via SQLAlchemy
web/        Next.js frontend — App Router, Tailwind, shadcn/ui, BlockNote
infra/      Docker Compose + Caddy config for self-hosted deployment
migrations/ Alembic schema migrations
agent/      (planned) AI automation and provider integrations
```

Sub-level CLAUDE.md files contain stack-specific conventions:
- `api/CLAUDE.md` — Python/FastAPI patterns, domain layout, JSONB conventions, habits/todos domain detail
- `web/CLAUDE.md` — Next.js patterns, UI primitive inventory, anti-patterns, habits/todos frontend detail
- `infra/CLAUDE.md` — local install (launchd/systemd), Docker Compose, NAS deployment

---

## Open-core boundary

**Always in the open core:** household model, all domain features (tasks, habits, documents, recipes, etc.), self-hosted deployment, basic AI/BYOK hooks.

**Candidates for paid/hosted tier:** managed hosting infrastructure, automated backups, polished mobile apps with push notifications, managed AI credits, premium integrations with ongoing operational cost.

If a design makes the self-hosted product feel crippled or fake, push back.

---

## Cross-cutting principles

- Domain logic lives in service layers, not routers or UI components.
- All writes go through service functions — no ad-hoc DB access from routes or frontend.
- Personal and household-shared data must be intentionally scoped; data leaking across scope boundaries is a design bug.
- Privacy by default — when uncertain, scope data more narrowly.
- Prefer straightforward, maintainable code over clever abstractions.
- Typed interfaces and explicit schemas everywhere (Pydantic on the API, TypeScript on the frontend).
- Avoid infrastructure disproportionate to the current phase.

---

## When unsure

1. Preserve privacy and data scope boundaries.
2. Keep the design portable across the three deployment tiers.
3. Prefer the simplest implementation that leaves future options open.
4. Ask for clarification when business-model or privacy implications are significant.
