# Agent proposals — a third tier between "can" and "can't"

Parent: `plans/open-hearth.md`. Status: **proposal-001 SHIPPED 2026-07-21** (model, tier
semantics, tool behaviour, audit double-attribution, expiry sweep). `proposal-002` (approval
queue UI, notifications, MCP status tools) and `proposal-003` (web-UI propose) remain.
Prereqs: PAT scopes (006), permissions_config ceilings, audit (008) — all shipped.

## Where proposal-001 landed

- `api/src/life_dashboard/proposals/` — `models.py` (the one table), `service.py` (record /
  approve / reject / sweep), `executors.py` (tool name → the function that performs its write).
- `auth/pat_scopes.py` — the `read < propose < write` ladder (`tier_rank`, `min_tier`,
  `scope_tier`) and a `check_scope` that refuses `propose` for a REST write.
- `core/permissions.py` — the opt-in `propose` threshold and `resolve_permission_tier`.
- `mcp/auth.py` — `authorize` returns an `AuthDecision` carrying the resolved tier.
- `mcp/server.py` — each write tool split into a thin tool and a registered `_perform_*`,
  so the approval path replays the same code the direct path runs.
- Migration `0051`. Tests: `api/tests/test_proposals.py`.

**One deliberate gap:** the proposed-status message tells the agent to call
`get_proposal_status(proposal_id)`, which proposal-002 adds. The copy is implemented verbatim
per this doc; land proposal-002 before that message is anything but forward-looking.

## The idea

Today an agent write either executes or errors. Proposals add a middle outcome: the write
is captured as a **pending proposal** that a human with sufficient permission approves or
rejects. "Joey's agent wants to add a todo for Lisa" stops being a 403 and becomes an
item in a parent's approval queue. Nobody in the household/agent space has this; it is
the natural extension of scope ∩ ceiling, and it safely unlocks domains currently too
sensitive for agents at all (a budget write could be propose-only even for adults'
agents — re-opening budget to the agent surface without trusting agents with money).

## Permission semantics

Extend both layers with a third value, ordered `read < propose < write`:

- **Token scopes:** `{"todos": "propose"}` becomes legal. Effective permission =
  min(token, ceiling) under this ordering.
- **Member ceilings:** `permissions_config` actions gain `propose` as an assignable rank
  outcome — e.g. todos `create` for `viewer`-rank members resolves to propose instead of
  deny. Backward compatible: existing configs never resolve to propose unless set.

Write tools change behavior in exactly one way: when `authorize(..., "write")` resolves
to `propose`, the tool records a Proposal instead of executing, and returns
`{"status": "proposed", "proposal_id": ..., "message": "This household requires approval
for this action; the household admins have been asked."}` — the message is part of the
tool contract so agents relay it naturally.

## Model

`proposals`: `id, household_id, proposed_by_user_id (nullable — household-agent),
token_id (nullable — web-UI proposals have no token), source, domain, tool,
args (JSONB — the exact would-be service call), summary (display string),
status (pending|approved|rejected|expired), decided_by, decided_at,
reject_reason, result_entity_id, created_at, expires_at (default 7 days)`.

`source` reuses the existing `AuditSource` vocabulary (`web|mcp|script`) rather than
inventing an `agent|web` one — `audit_log.source` already exists with those values, and two
columns named `source` with divergent vocabularies is a trap for whoever joins them on the
Activity page. `mcp` covers agent proposals, `web` covers proposal-003.

**Why a new table and not `audit_log`** (asked and settled 2026-07-20 — `audit_log` shares
~9 of these columns and is the obvious reuse candidate):

- `audit_log` is append-only; that is its defining property. Proposals mutate through
  `pending → approved/rejected/expired` and accumulate decision columns. UPDATE traffic on
  the audit table would make it something other than an audit log.
- **The FK semantics are inverted, and reuse would introduce a real bug.** `audit_log` uses
  `ON DELETE SET NULL` on `token_id` so rows outlive revoked tokens. The stale-proposer
  guard needs the opposite: it must tell a legitimately-null household-agent `token_id`
  apart from a token that was revoked after proposing. Under `SET NULL` those states are
  indistinguishable and the guard fails open. `proposals.token_id` must therefore NOT
  cascade to NULL — revocation has to stay detectable.
- `audit_log.payload` is contractually "a small summary, never the full row"; `args` must be
  the exact, complete service call because approval replays it. Same type, opposite contract.
- Retention differs: audit rows are permanent history, proposals expire and are swept.

Double-attribution needs both tables regardless — approval writes an `audit_log` row naming
proposer and approver.

**Migration surface is exactly one table.** The `read < propose < write` tier itself needs
no DDL: `personal_access_tokens.scopes` and `households.permissions_config` are both JSON
columns, so admitting `propose` as a value is a vocabulary change in `auth/pat_scopes.py`
and `core/permissions.py`.

- **Idempotent like everything else:** identical pending args → same proposal returned,
  not duplicated.
- **Approval executes the original write** through the same service function, attributed
  in `audit_log` as TWO facts: proposed_by (agent/token) and approved_by (human). The
  audit story is "Joey's speaker proposed it; Mom approved it."
- **Rejection with reason** is queryable by the agent (`get_proposal_status`) so it can
  close the loop with its user.
- Expiry sweep piggybacks on the existing APScheduler jobs.

## Surfaces

- **Approval queue:** dashboard widget + `/proposals` page (approve/reject with reason).
  Realtime: bus events `proposal.created` / `proposal.decided` (SSE already delivers;
  future webhook event for phone push via ntfy/HA).
- **MCP:** `list_my_proposals`, `get_proposal_status` for agents. Approving stays
  human/UI-only in v1 (an agent approving proposals defeats the point; revisit for
  admin-owned tokens later).
- **Voice personality hook:** the bridge can render `status: proposed` playfully
  ("I'll ask your parents"). Bridge-layer, optional, delightful.

### Agent-facing copy (implement verbatim)

Root CLAUDE.md: *tool descriptions and error messages are agent UX — write them with the
care given to UI copy.* These are the contract, not placeholders. The failure mode to avoid
is an agent reading `status: proposed` as an error and apologising to its user for a
failure that did not happen — so the copy states plainly that the action is pending, names
who is deciding, and says what to do next.

**Proposed-status response** — returned by every write tool when `authorize` resolves to
`propose`:

```json
{
  "status": "proposed",
  "proposal_id": "…",
  "expires_at": "…",
  "message": "Saved as a pending request — not yet done. This household requires
              approval for this action, and its admins have been notified. Tell the
              user their request is waiting on approval; do not retry or try another
              tool. Check back with get_proposal_status(proposal_id)."
}
```

**`list_my_proposals`**

> List the requests you have submitted on this member's behalf that are still awaiting a
> human decision, plus recently decided ones. Returns only your own proposals — never the
> household's full approval queue, and never another member's. Use this when the user asks
> what you are waiting on, or after a write returned `status: "proposed"`. Filter with
> `status`: `pending` (awaiting a decision), `approved` (executed), `rejected` (declined,
> with a reason), `expired` (nobody decided before `expires_at`). Omit `status` for all
> four. You cannot approve a proposal — approval is a human action taken in the Hearth app.

**`get_proposal_status`**

> Check what happened to one proposal you submitted, by `proposal_id`. Returns its status,
> who decided it and when, and — for a rejection — the reason the approver gave, which you
> should relay to the user in their own words rather than quoting verbatim. A `pending`
> result means nobody has decided yet; do not resubmit the underlying action, as an
> identical request returns this same proposal rather than creating a second one. Unknown
> id: see `list_my_proposals` for the ids you own.

**Error on unknown/foreign id** — must name the problem and the way forward, never a bare
404:

> No proposal with that id belongs to this token. It may have been submitted by a different
> member or device, or it may have expired and been cleaned up. Call `list_my_proposals` to
> see the proposals you can check.

**Refused-approval message** (stale proposer, surfaced in the UI to the approving human):

> Can't approve this — the token that requested it has been revoked. Ask for the action
> again from a current device.

## Device tiers & the overload problem (decided direction, 2026-07-17)

Per-speaker linking is structurally impossible on Alexa/HA anyway — account linking is one
OAuth link per platform account, so every speaker in the house arrives on ONE
household-agent token. Differentiation happens inside Hearth via a device-profile layer:

- **Zero-config default:** any device on the household-agent token acts at the base agent
  tier (propose for guarded domains, write where permissions_config allows). A new,
  unmapped speaker is already correctly restricted.
- **Opt-in exceptions:** `device_profiles` table mapping the platform's device id (Alexa
  `context.System.device.deviceId`; HA satellite/area) → elevated tier. Settings → Devices
  auto-lists device ids as they are first seen ("seen, unmapped"); admins promote the few
  that matter (parents' bedroom → write tier). Defaults + exceptions, never per-device
  setup burden.
- **Hard rule — approval surface:** voice devices max out at `write` (skip the queue for
  their own actions). APPROVING other actors' proposals happens only on authenticated
  surfaces (app/push). Device identity proves where a request came from, never who spoke —
  "Joey walks into the parents' room" is the threat model. Voice ID may revisit this later;
  it remains attribution, not authentication.
- Agents and members share one permission system by design: the household-agent is a
  member with a role; promoting a trusted device and promoting a grown kid are the same
  lever.

## Decided (2026-07-20)

**Approval re-validates against the approver, not the proposer.** Approval is the
approver's own act: execution re-runs `authorize(...)` as the approving member, requiring
`write` on the domain. The proposer's ceiling already did its job — it is what routed the
call to `propose` in the first place — and re-checking it at decision time would let a
proposer's later demotion silently void a decision an admin legitimately made.

One guard rides along, on audit-integrity grounds rather than permission grounds: approval
**refuses** a proposal whose `token_id` has been revoked, or whose `proposed_by_user_id` has
left the household. Executing those would write an audit row attributing the action to a
credential that no longer exists, breaking the "Joey's speaker proposed it; Mom approved it"
story that is the whole point of double-attribution. Refused proposals move to
`status="expired"` with a reject_reason explaining the credential is gone.

**Notification routing: all admins, configurable later.** `proposal.created` fans out to
every owner/admin in the household. The queue is shared and first-to-decide wins — a second
admin opening an already-decided proposal sees the decision and who made it, not a stale
approve button. No routing configuration in the schema for now. This follows the same
defaults-plus-exceptions shape as the device-tier model above: ship the correct default,
add the exception layer when a household actually asks for it. Per-domain approver routing
(budget → the finance-managing adult) is the natural v2 and lands in `permissions_config`
when it does.

**Propose-only will extend to the web UI, but not yet.** A restricted member submitting a
todo from the app and landing it in the same approval queue is a genuine product feature,
not just an agent affordance — it is the difference between "the agent asks permission" and
"Hearth models household permission." It is deferred to a `proposal-003` so proposal-001
stays scoped to the agent surface.

The commitment binds proposal-001's model regardless: the proposals table is built
**surface-agnostic from day one**. `proposed_by_user_id` is nullable (household-agent),
`token_id` is nullable too (a web-UI proposal has no token), and a `source` column
(`agent|web`) records which surface a proposal came from. No column added later, no
backfill — proposal-003 adds a branch in the REST write path and reuses the table whole.

## Open questions

- Batch approval UX — deferred to proposal-002's design pass; the model supports it either
  way (decide N rows in one transaction), this is purely a queue-UI question.

## Log

- **2026-07-17** — Design drafted alongside outbound-webhooks as a track-7 agent-native
  follow-on. Permission semantics, model, surfaces, and the device-tier/overload direction
  recorded; three open questions left for a dedicated thread.
- **2026-07-20** — Spec session. All three open questions decided: approval re-validates
  against the **approver** (must hold `write`), with a stale-proposer refusal added on
  audit-integrity grounds; notification routes to **all admins**, configurable later;
  web-UI propose is **committed but deferred to proposal-003**, which forces
  `token_id` nullable and a `source` column in proposal-001's table so no migration is
  needed later. Agent-facing copy for `list_my_proposals`, `get_proposal_status`, and the
  proposed-status response written verbatim into this doc per the parity principle.
  `proposal-001` (19 steps) and `proposal-002` (18 steps) filed in `feature_list.json`.
  No code written — a separate build was in flight, so execution was left to a CLI session.

- **2026-07-21** — `proposal-001` built. One table (`0051`), replayed clean on Postgres and
  applied forward on SQLite; the partial unique index and the CASCADE-not-SET-NULL `token_id`
  verified in both real databases. Decisions that firmed up during the build:
  - The propose ceiling is an **opt-in `propose` key** inside a domain's action config
    (`{"todos": {"create": "member", "propose": "viewer"}}`), with no default. That is what
    makes the backward-compatibility guarantee mechanical rather than a promise:
    `merge_with_defaults` never invents the key, so no existing household can resolve to
    propose.
  - Idempotency is a **SHA-256 fingerprint over (tool, args, proposer, token)** under a
    partial unique index, not a JSON comparison. JSON equality is not portable across
    Postgres and SQLite, and folding the two nullable proposer columns into the digest makes
    them dedupe correctly — SQL NULLs never compare equal, so a NULL-bearing unique index
    would let every household-agent proposal through.
  - Deciding is an **atomic claim** (`UPDATE … WHERE status='pending' RETURNING id`), not a
    `SELECT … FOR UPDATE`. The executor's own service call commits, which would release the
    lock mid-approval; the claim is what actually stops two admins executing one write twice.
  - Each write tool split into a thin tool plus a registered `_perform_*`. "Approval executes
    through the same service function" is now structural rather than a convention — there is
    only one copy of the write.
  - The proposed-status copy is implemented verbatim, including its forward reference to
    `get_proposal_status`; see the gap note at the top.

## Suggested feature entries

- `proposal-001` — model + scope/ceiling `propose` semantics + tool behavior + audit
  double-attribution (migration: yes → serialize with other migration-bearing builds).
- `proposal-002` — approval queue UI + realtime/notification + MCP status tools + voice
  rendering.
- `proposal-003` — web-UI propose for restricted members (REST write paths branch to
  propose; reuses the proposal-001 table unchanged).
