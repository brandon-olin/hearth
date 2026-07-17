# Open Hearth — open protocols, open data, agent-native direction

Anchor doc for the "open Hearth" initiative. This file holds the vision, the tracks, their
status, and cross-cutting decisions. Per-track detail lives in `plans/open-hearth/<track>.md`,
created lazily when a track's design thread starts.

**How to use this doc (for Claude sessions):** read this file at the start of any thread
touching one of the tracks below. At the end of the thread, write decisions back to the
track doc and update the status line here. Only record **decisions** and **open questions**
in this file — discussion and maybes stay in the track docs or nowhere.

---

## Vision

Hearth should embody the open-software ideals it was inspired by (open protocols like
ActivityPub, local-first tools like Home Assistant, agent-legible systems): your household's
data lives in your house, speaks open formats and protocols, is never locked in, and is
operable by any AI agent you choose — with the household's privacy boundaries enforced.

This is both product strategy (openness is the moat, per the Ghost model — open core + paid
managed hosting) and personal signaling (public commitment to open protocols and data
ownership).

Guiding constraints, inherited from root CLAUDE.md:

- Protocol adapters and exporters call existing domain services — no new data paths.
- The shared / personal / sensitive data-scope model is the permission boundary for
  everything external (agents, feeds, federation).
- Everything must work across all three deployment tiers (local, NAS, cloud).
- No schema refactors required by this initiative; these are projection/adapter layers.

---

## Tracks

Sequenced in dependency order — earlier tracks settle decisions later tracks inherit
(MCP forces the scoped-token design; HA inbound forces the event bus).

### 1. MCP server — *COMPLETE 2026-07-17 — full chain shipped: PATs (006), read-only (mcp-001), writes + household-agent (mcp-002), audit (008), OAuth (007)*

Any agent (Claude, OpenClaw, etc.) gets structured access to the household via a first-class
MCP server. Tools map 1:1 to existing service functions. Data-scope model = agent permission
model: an agent acting for a member sees shared + that member's personal data, never
sensitive or other members' personal scope.

- Empty `api/src/life_dashboard/mcp/` package already exists.
- Phasing: read-only tools → writes (idempotency principle already fits agent retries) →
  resources/prompts.
- **Decided (2026-07-17):** in-process FastMCP mount at `/mcp`; auth via per-member
  Personal Access Tokens (hashed, scoped, revocable — the standard pattern in self-hosted
  apps: Home Assistant long-lived tokens, Gitea scoped tokens, Immich/Mealie API keys);
  v1 tool surface is read-only (todos, habits, grocery, calendar, household summary;
  budget/documents/notes excluded). Prior-art notes and write-phase permission model in
  the track doc.
- Track doc: `plans/open-hearth/mcp-server.md`.

### 2. Open data — exports & imports — *NOT STARTED*

Every domain exports to open formats (Markdown for notes/docs, iCal for calendar-ish,
JSON/CSV for the rest). Imports from the apps people are escaping (Cozi, AnyList, Todoist,
Google Calendar). Pure serializer layer over existing services; zero schema changes.

### 3. Open protocol feeds — *NOT STARTED*

Read-only iCal feed URLs first (one GET endpoint per feed, secret-token auth, ~cheap).
RSS for meal plans/routines if useful. Full two-way CalDAV/CardDAV is a real protocol
implementation — deferred until feeds prove demand.

### 4. Home Assistant integration — *PARTIAL — REST bridge (voice-001) shipped 2026-07-17; inbound/event bus pending (realtime-001)*

Integrate, don't compete: HA owns devices, Hearth owns the people layer.

- **Inbound first:** HA webhooks → Hearth endpoint → internal event bus (empty `events/`
  package exists) → domain actions ("dryer finished" → fold-laundry chore for assignee).
- **Outbound later:** HACS custom integration exposing chores/meal plans as HA calendar
  entities. Also a marketing channel to exactly the right audience.

### 5. Federation & identity (ActivityPub-shaped) — *DECLARED DIRECTION, NOT SCHEDULED*

Household-to-household sharing: each household is an ActivityPub Actor, "follow" = sharing
invite, grocery lists/recipes as shared objects. Longer-term: a Hearth instance as an
OIDC/IndieAuth identity provider ("log in with your Hearth" — the anti-"log in with Google").

Note: ActivityPub federates content, not portable identity — identity portability is the
separate OIDC/IndieAuth (or AT Protocol DID) thread. Full AP (WebFinger, HTTP signatures,
inbox delivery) is the heaviest item on this list; stays a declared direction for now.

### 6. Signaling — *CROSS-CUTTING, marketing-site phase*

Manifesto page on gethearth.net ("your data, your house, open protocols"), public roadmap,
blog posts on design decisions (often higher hiring-signal value than the features).
Coordinate with `plans/marketing-site-spec.md`.

---

## Cross-cutting decisions

| Decision | Status | Notes |
|---|---|---|
| License | **DECIDED 2026-07-17: AGPL-3.0** | Switched from MIT while Brandon is sole copyright holder. LICENSE + README updated. Prior snapshots remain MIT. Add DCO/CLA before first outside contributor for future flexibility. |
| Scoped API token design | OPEN — MCP track owns this | Per-member tokens with scope claims; reused by feeds, HA, federation. |
| Internal event bus | DIRECTION SET — filed as `realtime-001` | `events/` package. In-process asyncio pub/sub keyed by household; swappable to PG LISTEN/NOTIFY. Consumers: real-time UI (SSE invalidation), HA track, notifications/automations later. |
| MCP transport & mounting | OPEN — MCP track owns this | FastMCP mounted in FastAPI vs separate process; localhost (tier 1) vs Tailscale HTTP (tier 2). |

---

## Open questions

- Write-phase permission model: decided — "member ceiling ∩ token scope" (see MCP track
  doc). Member ceiling already implemented (roles incl. `agent` + per-domain
  `permissions_config` in `core/permissions.py`); only the token-scope layer is new.
- Shared-device identity: direction set — hybrid (member-owned tokens for personal devices,
  household-agent pseudo-member for shared devices); details in MCP track doc.
- Feed auth: secret-token URLs good enough, or scoped tokens from day one?
- Does federation need its own protocol work, or is a documented server-to-server API a
  legitimate first step before full ActivityPub?

---

## Log

- **2026-07-17** — Doc created from initial brainstorm session. MCP track opened.
- **2026-07-17** — MCP decisions 1–4 recorded (in-process mount, PATs, read-only v1,
  permission = member ∩ token). Track doc created at `plans/open-hearth/mcp-server.md`.
- **2026-07-17** — SHIPPED: security-006 (PATs), mcp-001 (read-only MCP server), voice-001
  (HA REST bridge) — all merged to main, passes=true. mcp-002 + security-008 building.
- **2026-07-17** — LICENSE DECIDED: switched MIT → AGPL-3.0 (sole-author window, zero
  consent needed). Future HA integration path noted: HACS custom integration with UI config
  flow + zeroconf discovery replaces YAML/token paste; core-HA upstream submission as the
  long-term option.
- **2026-07-17 (evening)** — mcp-002 + security-008 + security-007 shipped (after a prod
  migration collision with the legacy baseline audit_log table — fixed by guarded drop in
  0044). realtime-001 shipped (event bus + SSE live; passes=true). voice-002 CODE shipped
  (voice/ module + docs/alexa-skill-setup.md — note: landed inside the realtime commit
  82c9816, protocol slip), passes=false pending real-world verification: Amazon dev account
  → console skill setup → account linking (check PKCE exemption for Alexa's confidential
  client) → physical Echo test. MCP track and its whole dependency chain are now DONE.
- **2026-07-17** — Event bus direction set via `realtime-001` (feature_list.json):
  bus + SSE invalidation stream for real-time UI; skinny events (no payloads), scope-filtered
  per connection. Same bus feeds HA inbound (track 4) when that track opens.
