# Roadmap

## Phase 0 (Weeks 1–2): Scope lock

- Freeze v1: single household, members, chores/todos, events, recipes, local/self-hosted only.
- Confirm DB model for: `household`, `household_member`, `task/chore`, `event`, `recipe`.
- Centralize DB access so `DATABASE_URL` is the only difference between NAS vs hosted deployments.

## Phase 1 (Weeks 3–6): Core vertical slice

Goal: one household can actually use it locally.

- Implement household + member management (create, update, basic roles).
- Implement chores/todos with assignments to members.
- Implement events (single + recurring) with assignments.
- Build a simple household dashboard showing upcoming events and current chores/todos by member.

## Phase 2 (Weeks 7–10): Daily-value features

Goal: the app feels useful week to week for a real household.

- Recipe CRUD UI (manual entry).
- Recipe import from URL via JSON-LD:
  - backend endpoint to fetch HTML,
  - parse `<script type="application/ld+json">`,
  - extract `Recipe` and map into the internal schema.
- Improved views/filters:
  - per-member view,
  - per-day / per-week calendar view.

## Phase 3 (Weeks 11–14): Self-hosted polish

Goal: a self-hosted v1 that another technical household could realistically run.

- Docker or deployment docs for running the frontend, FastAPI backend, and Postgres (or connecting to NAS Postgres).
- Basic auth/session model suitable for a single household.
- Backups/export story (dump/restore scripts or documented flow).
- Error handling, logging basics, and minimal tests for critical flows.

## Phase 4 (Weeks 15–24): Hosted-ready seams

Goal: prepare for a future hosted tier without building the full hosted product yet.

- Remove NAS-specific assumptions; ensure `DATABASE_URL` controls the target DB.
- Add iCal export feeds for events (per household or per member).
- Do a light permissions/privacy pass: clearly mark shared vs personal vs sensitive fields.
- Document a manual migration path from NAS/self-hosted to hosted Postgres.

## Defer for later

- Inter-household sharing.
- Real-time collaboration.
- Mobile apps.
- Payments.
- Deep third-party integrations.
- Full hosted multi-tenant production infrastructure.