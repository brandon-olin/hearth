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

### 7. Agent-native follow-ons — *DESIGN DRAFTS READY*

Post-MCP work that deepens the "software is APIs agents talk to" position:

- **Outbound webhooks** — *DESIGN SETTLED 2026-07-20; filed as `webhook-001` /
  `webhook-002`; not yet built.* Hearth as event source; design in
  `plans/open-hearth/outbound-webhooks.md`. Bus exists (realtime-001) but emits
  **table-level invalidations, not semantic events** — `webhook-001` builds the semantic
  layer as a prerequisite. Migration-bearing: serialize against `proposal-001`.
- **Agent proposals** — *SPEC COMPLETE 2026-07-20 — filed as `proposal-001` /
  `proposal-002`, ready to build.* Third permission tier `read < propose < write`;
  approval queue; design in `plans/open-hearth/agent-proposals.md`. Safely re-opens
  sensitive domains (budget) to agents. Decided: approval re-validates against the
  approver's ceiling; notifications fan out to all admins; web-UI propose for restricted
  members is committed but deferred to `proposal-003` (model built surface-agnostic so it
  needs no migration).
- **MCP resources** — `household://today` aggregate (shared with the Dashboard rebuild;
  one `today` service feeding REST + MCP + eventually feeds). Decided: dashboard widgets
  stay user-customizable but render slices of the today payload — the dashboard shows the
  same JSON the agent reads.
- **Tool-surface growth** — priority adds: `complete_todo`, `list_members` (+
  `assigned_to` on `add_todo`), `check_off_grocery_item`, recipe reads +
  `add_recipe_to_grocery_list`. Description quality bar now in root CLAUDE.md
  ("No feature ships without its MCP verb").

## Cross-cutting decisions

| Decision | Status | Notes |
|---|---|---|
| License | **DECIDED 2026-07-17: AGPL-3.0** | Switched from MIT while Brandon is sole copyright holder. LICENSE + README updated. Prior snapshots remain MIT. Add DCO/CLA before first outside contributor for future flexibility. |
| Scoped API token design | OPEN — MCP track owns this | Per-member tokens with scope claims; reused by feeds, HA, federation. |
| Internal event bus | SHIPPED as `realtime-001` — **semantic layer pending in `webhook-001`** | `events/` package. In-process asyncio pub/sub keyed by household; swappable to PG LISTEN/NOTIFY. **What shipped emits table-level invalidations only** (`entity_type`=tablename, `action`=created/updated/deleted) via universal SQLAlchemy `after_flush`/`after_commit` listeners — there are no named domain events and no `bus.publish` calls under `domains/`. Named semantic events (`todo.completed`, `grocery.item_added`, …) are built by `webhook-001` on the same commit-time plumbing. Child tables without `household_id` (`grocery_items`, `habit_occurrences`) emit nothing today. Consumers: real-time UI (SSE invalidation), outbound webhooks, HA track, notifications/automations later. |
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
- **2026-07-17 (late)** — Agent-native follow-ons designed (track 7 above): outbound
  webhooks + agent proposals drafted as track docs for their own threads; parity principle
  ("No feature ships without its MCP verb") added to root CLAUDE.md; tool-surface gaps
  identified (complete_todo, list_members/assignee, check-off, recipes);
  `household://today` resource tied to the Dashboard rebuild.
- **2026-07-20** — Agent proposals spec session: three open questions closed (approver
  re-validation, notification routing, web-UI propose), agent-facing tool copy written,
  `proposal-001` + `proposal-002` filed. Track doc status → SPEC COMPLETE. A third entry,
  `proposal-003` (web-UI propose for restricted members), is named in the track doc but not
  yet filed — it is a product feature beyond the agent surface and wants its own thread.
- **2026-07-20** — Outbound webhooks spec session. **Correction of record: the track doc's
  event catalog was fiction.** It claimed to be "derived from what the bus already emits";
  in fact `events/emit.py` is a universal table-level invalidation producer with zero named
  domain events, so four of the six proposed events (`todo.completed`,
  `grocery.item_added`, `grocery.item_checked`, `habit.checked_in`) could not be delivered —
  including both halves of the doc's own flagship demo. `grocery_items` and
  `habit_occurrences` carry no `household_id` and emit nothing at all. DECIDED: `webhook-001`
  builds a semantic event layer on the existing commit-time plumbing (service functions
  stash a `SemanticEvent` on `session.info`; the existing `after_commit` listener publishes
  it), with `events/scope.py` `can_see` widened to serve both event kinds — no second scope
  mechanism. Four open questions closed: central summary allowlist (not per-domain methods);
  `webhook_deliveries` for attempts + `audit_log` for subscription lifecycle only; patterns
  as the sole v1 filter surface; HA preset = docs recipe now, UI prefill later, never a
  payload variant. `webhook-001` + `webhook-002` filed. Also noted: the "sensitive" data
  scope in root CLAUDE.md has no counterpart in `core/visibility.py`
  (`household|personal|members`) — worth reconciling the vocabulary. Track doc status →
  DESIGN SETTLED. Build not started; `webhook-001` is migration-bearing and must serialize
  against `proposal-001`.
- **2026-07-17** — Event bus direction set via `realtime-001` (feature_list.json):
  bus + SSE invalidation stream for real-time UI; skinny events (no payloads), scope-filtered
  per connection. Same bus feeds HA inbound (track 4) when that track opens.
