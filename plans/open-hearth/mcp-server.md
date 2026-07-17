# MCP Server — track doc

Parent: `plans/open-hearth.md`. Status: **design phase, active.**

Goal: any agent (Claude, OpenClaw, HA voice assistant) gets structured access to the
household via MCP, with the shared/personal/sensitive data-scope model enforced as the
permission boundary.

---

## Decisions

1. **In-process mount.** FastMCP (official Python SDK) mounted into the existing FastAPI
   app as a sub-application — `/mcp` streamable-HTTP endpoint on the API port (1338).
   No separate daemon. MCP tools live in `api/src/life_dashboard/mcp/` and call domain
   services directly (same rule as routers).
2. **Auth via Personal Access Tokens (PATs).** New table: per-member, stored hashed,
   shown once at creation, individually revocable, with scope claims (domain × read/write).
   Existing session JWTs are too short-lived for agents. The PAT primitive is reused later
   by iCal feeds, HA webhooks, and federation.
3. **v1 is read-only.** Initial tool surface: `list_todos`, `list_habits` (+ streaks),
   `get_grocery_list`, `list_calendar_events`, `get_household_summary`. Budget, documents,
   and notes are excluded from v1 (sensitive-data concentration).
4. **Effective permission = member permission ∩ token scope.** A token can never exceed
   what its owning member may do in the app. Direction for the write phase; details below.

## Prior art — PATs in self-hosted / open-source apps

The PAT table is the standard pattern in exactly this space:

- **Home Assistant** — "Long-Lived Access Tokens": created from the user profile page,
  ~10-year expiry, listed and revocable individually, stored server-side as a record tied
  to the user. The canonical reference for a self-hosted household system.
- **Gitea / Forgejo** — scoped access tokens with per-resource-category read/write scopes
  (`read:issue`, `write:repository`). Best open-source reference for the scope model.
- **GitHub fine-grained PATs** — proprietary, but the UX benchmark for per-resource
  read/write granularity and token-management UI.
- **Immich** — per-user API keys, recently extended with granular permissions; good example
  of shipping coarse keys first and tightening later.
- **Mealie** — per-user long-lived API tokens in a household-domain app.
- **Paperless-ngx / Jellyfin** — plain per-user API keys; the minimum viable version.

Implementation conventions to copy: store only a hash of the token; display the secret
once at creation; use a recognizable prefix (e.g. `hearth_pat_...`) so tokens are
identifiable in logs and secret scanners; record `last_used_at` for the management UI.

## Write phase — permission model (in discussion)

Voice/agent flows make creates unavoidable early ("add a todo for Brandon to mow the lawn,
due Friday"), so read-only is a phase, not a stance.

Layered model under discussion:

- **Layer 1 — member ceiling (role-based). ALREADY BUILT.** `MembershipRole` has
  owner/admin/member/viewer/**agent** (agent = rank 1, viewer-level default), and
  `Household.permissions_config` gives admins per-domain control over `read` / `create` /
  `manage_others` by minimum role (`core/permissions.py`). Kids = member or viewer role;
  admins tune per-domain what each rank can do. The PAT work only adds Layer 2.
- **Layer 2 — token scopes (per-token, domain × read/write).** Chosen at token creation:
  "this OpenClaw token may read+write todos and grocery lists, read calendar, nothing else."
  Sensible defaults: write on for todos/grocery/calendar, off for budget/documents.
- **Effective permission = Layer 1 ∩ Layer 2.** No per-tool grant matrix for now — domain ×
  read/write is the granularity; per-tool granularity is a possible later refinement if
  demand appears.

Note on assignment vs. scope: "create a shared todo assigned to Brandon" is a shared-scope
write by the token's owning member — allowed for adults, not for restricted members.

## Device identity — hybrid model (direction, 2026-07-17)

Token ownership follows the device, not a single rule:

- **Personal devices** (speaker in a member's bedroom, a member's phone/laptop agent) →
  **member-owned token**. The member's role ceiling applies automatically (kid's bedroom
  speaker inherits the kid's restrictions for free). Accountability maps to a person.
- **Shared devices** (kitchen speaker, parents' shared bedroom speaker, household OpenClaw
  instance) → **household-agent pseudo-member token**. The `agent` membership role already
  exists (rank 1). Pseudo-member = a user account with membership role=agent; admins control
  what it can do per domain via the existing `permissions_config` (same UI/mechanism as for
  other members). Never personal or sensitive scope, never an assignee. Honest audit
  attribution ("kitchen speaker added milk"), survives member deactivation, no impersonation.

Known limits: the pseudo-member can't act on personal scope ("add to MY list" is ambiguous
without speaker identification); it needs the member-role model anyway, so it ships in the
write phase, not v1. Pseudo-member is excluded from assignment semantics (never an assignee).

## Audit wiring (design sketch)

`audit/` package is currently an empty placeholder — MCP writes bootstrap it.

- Table `audit_log`: id, household_id, actor_user_id (nullable for pseudo-member),
  token_id (nullable — null = web session), source (`web` | `mcp` | `script`), action,
  entity_type, entity_id, payload JSONB (summary, not full row), created_at.
- Service: `audit.service.record(...)` — called from a decorator wrapped around every MCP
  write tool, so tool authors can't forget it. Web routes can adopt the same call later.
- Surface: eventually a settings "Activity" page (who/what/via which token); until then
  it's queryable.

## Cloud tier note

Same code path: hosted households get `https://<household-domain>/mcp`, agents authenticate
with the member's PAT as a Bearer token. Works today with Claude Code/desktop-style clients
(custom headers). Consumer-grade "Connect Hearth" buttons in hosted agent UIs increasingly
expect OAuth 2.1 dynamic client registration — treat OAuth-in-front-of-PATs as a cloud-tier
follow-up, not a v1 requirement. Cloud additionally needs per-token rate limiting.

## Voice platform strategy (2026-07-17)

Decision: **all voice speakers are shared devices** in the write phase — every speaker gets
a household-agent token restricted to shared scope. Consequences accepted: no personal-scope
actions by voice ("add to my private list" isn't possible from a speaker). Shared todos,
grocery, and calendar are the natural voice domain anyway, and this collapses the
per-device-classification problem to zero config.

Reframe that falls out: the personal-vs-shared split was never really about speakers.
**Personal agents** (Claude on a member's phone/laptop, a personal OpenClaw instance, CLI)
already know who the user is via login → member-owned tokens. **Speakers** don't → shared
household-agent tokens. Clean line, no per-device settings.

**Kid-mischief guards** (e.g. Joey voice-completing his own chore, or creating prank todos
for his sister) map onto the existing permission actions:

- "Mark X's todo complete" where the todo was created by a parent = `manage_others` —
  blocked for the speaker's agent role under defaults.
- Prank creates: admins tune `create` per domain in `permissions_config` — e.g. grocery
  `create` = everyone (speaker can add milk), todos `create` = member+ (speaker can't
  create todos at all). Coarse but zero new code; per-utterance guarding needs speaker ID.

Speaker identification (Alexa voice profiles, Google voice match, HA local speaker ID):
treat as *convenience attribution*, never authentication — reliability is household-grade,
not security-grade. If added later, it may upgrade attribution on a shared device — audit
author stays the speaker's pseudo-member, with "probably Brandon" recorded in the audit
payload — but must never unlock personal or sensitive scope by itself. Soft/playful
enforcement (the speaker declining a prank with personality) is a bridge-layer behavior,
fine to gate on voice ID since a misfire costs nothing. Bridge-when-we-get-there.

Multi-platform containment (the scope-blowup guard): Hearth integrates with **zero speaker
platforms directly**. Hearth exposes one interface (MCP + REST, PAT auth); platform bridges
are thin adapters calling that same API — HA integration (`voice-001`), Alexa skill
(`voice-002`), whatever comes next. Each bridge holds its own household-agent token. All
permission logic lives server-side in the token model, so adding a platform never adds
permission code.

## Build concurrency

Sequential spine: security-006 → mcp-001 → (mcp-002 + security-008 jointly). Parallel lanes
after 006 lands: voice-001 alongside mcp-001 (disjoint code — bridge docs/settings vs mcp/
package; caveat: its household-agent PAT formally arrives with mcp-002 provisioning, so
first-pass with a member PAT and swap, or pull provisioning forward). security-007 waits
for a consumer (cloud connectors or voice-002). Practical rule for parallel Claude CLI
sessions: serialize anything that adds an Alembic migration (006 = PAT table, 008 = audit
table — two branches each adding migrations create dual heads); migration-free tasks
(mcp-001, voice-001) parallelize safely. Both parallel sessions appending to
claude-progress.txt / feature_list.json will conflict — trivial to resolve, but expect it.

## Open questions

- ~~Member roles beyond admin~~ RESOLVED: full role system (owner/admin/member/viewer/agent)
  and admin-tunable per-domain permissions already exist in `core/permissions.py` +
  `Household.permissions_config`.
- Token expiry policy: HA-style ~10 years vs. 1 year with renewal.
- Speaker identification on shared devices (HA/voice assistants support this partially) —
  could later map a shared device's request to a member identity for personal-scope actions.

## Log

- **2026-07-17** — Track opened. Decisions 1–4 recorded; prior-art survey added; write-phase
  permission model drafted (member ceiling ∩ token scope).
- **2026-07-17** — PAT build task filed as `security-006` in `feature_list.json` (Brandon
  building via Claude CLI). Device identity direction set (hybrid: member-owned tokens for
  personal devices, household-agent pseudo-member for shared devices). Audit design sketch
  and cloud-tier note added.
- **2026-07-17** — OAuth 2.1 cloud-tier layer filed as `security-007` (phase: later); audit
  log filed as `security-008` (phase: v1.1). Voice platform strategy decided: all speakers
  are shared devices (household-agent token, shared scope only); personal agents (phone/
  laptop/CLI, login-authenticated) use member-owned tokens; speaker ID is attribution-only,
  never authentication; platform bridges (HA, Alexa) are thin adapters over the one MCP/REST
  interface — no per-platform permission logic.
- **2026-07-17** — Discovery: Layer 1 already exists. `MembershipRole` includes an `agent`
  role (rank 1) and `Household.permissions_config` provides admin-tunable per-domain
  read/create/manage_others — the pseudo-member and admin-control design Brandon proposed
  is the existing mechanism. Member-roles open question resolved; kid-mischief guards map
  to `manage_others`/`create` config. Attribution decision: audit author = speaker
  pseudo-member, voice-ID guess recorded in payload.
- **2026-07-17** — MCP server v1 filed as `mcp-001` in `feature_list.json` (Integrations,
  phase v1.1, depends on security-006). Build order: security-006 → mcp-001 → security-008
  (with write phase) → security-007 (cloud).
- **2026-07-17** — `voice-001`/`voice-002` reconciled with this design (UPDATE paragraphs
  appended in feature_list.json): their planned `integration_token` type is superseded by
  household-agent PATs; voice-002 gains a dependency on security-007 because Alexa account
  linking requires OAuth; personal-scope intents reframed as shared-scope queries.
- **2026-07-17** — Write phase filed as `mcp-002` (write tools + household-agent
  provisioning + audit decorator; build jointly with security-008). Testing note added to
  voice-001: HA runs as a local Docker container, no hardware needed; Alexa speakers are
  voice-002's path, not voice-001's.
