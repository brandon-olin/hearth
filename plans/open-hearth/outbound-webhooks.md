# Outbound webhooks — Hearth as an event source

Parent: `plans/open-hearth.md`. Status: **DESIGN SETTLED 2026-07-20 — ready to build,
filed as `webhook-001` / `webhook-002`. Not yet started.**
Prereq: internal event bus (shipped, `realtime-001`) — but see the catalog audit below: the
bus emits table-level invalidations, not semantic events, so `webhook-001` must build the
semantic layer first. Sibling: HA inbound (unfiled).

## Why

Agents and other systems can currently *act on* Hearth (MCP) but cannot *react to* it.
Outbound webhooks make Hearth a peer in other people's automations: "when a chore is
completed, POST here" — HA automations, n8n flows, a family Discord bot, another
household's agent. This is the second half of the "software is APIs AI talks to" position:
Hearth emits, not just receives. It is also the mirror image of HA inbound — one bus in
the middle, webhooks out one side, webhooks in the other.

## Design

**Subscriptions** — new table `webhook_subscriptions`:
`id, household_id, created_by (member), url, secret (hash? no — needed for signing, store
encrypted via FIELD_ENCRYPTION_KEY), event_patterns (JSONB, e.g. ["todo.completed",
"grocery.*"]), active, consecutive_failures, last_delivery_at, created_at`.

**Scope rule (the important one):** a subscription is member-owned and delivers only
events its owner is entitled to see — the exact same filter the SSE stream applies
per-connection (`events/scope.py` is reusable as-is). Household-agent-owned subscriptions
therefore get shared-scope events only. Sensitive-scope events are never delivered to
webhooks at all in v1 (stricter than SSE; revisit later).

**Payloads are skinny, like SSE:** `{event, entity_type, entity_id, household_id,
occurred_at, summary}` where `summary` carries only non-sensitive display fields (a todo
title, an item name). Receivers wanting more fetch back through the REST API with their
own credentials — keeps scope enforcement in one place.

**Delivery semantics:**
- Async worker consuming from the bus (same in-process pattern; a queue table
  `webhook_deliveries` gives durability + at-least-once with a delivery id for receiver
  dedupe).
- Signature: `X-Hearth-Signature: t=<unix>, v1=HMAC-SHA256(secret, t + "." + body)` —
  timestamped to block replay. Document receiver verification in the API docs.
- Retries: exponential backoff (e.g. 30s/5m/30m/2h/6h), then mark failed; auto-disable
  the subscription after N consecutive delivery failures (Stripe-style), surface in UI.
- Timeout ~5s; response body ignored; 2xx = delivered.

**SSRF guard (tier-dependent):** cloud tier rejects private/loopback ranges and
re-resolves DNS at delivery; self-hosted allows LAN targets (pointing at your own HA box
is the whole point). `DEPLOYMENT_TIER` already exists to key this.

## Event catalog — verified against the code 2026-07-20

**The original draft of this section was wrong.** It claimed the catalog was "derived from
what the bus already emits." It was not: `events/emit.py` is a *universal table-level
invalidation producer*, not a semantic event emitter. Two SQLAlchemy listeners
(`after_flush` / `after_commit`) sweep every household-scoped row touched in a transaction
and publish `InvalidationEvent(entity_type=<tablename>, action="created"|"updated"|"deleted")`.
There are zero `bus.publish` / `emit` calls anywhere under `domains/` — no named domain
event exists today.

Audit of the originally-proposed catalog:

| Proposed event | Reality as of 2026-07-20 |
|---|---|
| `todo.created` | Exists as `todos` + `created` |
| `todo.completed` | **Absent.** A completion is `todos` + `updated`, indistinguishable from a title edit — the producer deliberately discards which fields changed |
| `grocery.item_added` | **Cannot emit.** `grocery_items` has no `household_id`, so the universal producer skips it (see emit.py "coverage caveat") |
| `grocery.item_checked` | Same — no emission at all |
| `habit.checked_in` | Same — `habit_occurrences` has no `household_id` |
| `calendar.event_created` | Exists as `calendar_events` + `created` |

Four of six could not be delivered, including both halves of this doc's own flagship demo
(an agent subscribing itself to `grocery.item_added`). `proposal.*` is also not available:
the agent-proposals build has not landed — only `plans/open-hearth/agent-proposals.md`
exists.

### Decided 2026-07-20 — semantic event layer, built as part of webhook-001

The universal producer stays exactly as-is (it feeds SSE invalidation; changing it breaks
live UI). Semantic events are added as a **parallel payload on the same commit-time
plumbing**:

- Domain service functions append a `SemanticEvent` to `session.info` under its own key,
  mirroring `_PENDING_KEY`. The existing `after_commit` listener publishes them alongside
  the invalidations.
- This inherits the proven guarantees for free: nothing emits for a transaction that then
  rolls back, and publish failures never break the committed write.
- **Child tables become emittable.** `grocery_items` / `habit_occurrences` can't emit from
  the universal producer, but the service function knows the parent, so it emits explicitly
  with the parent's `household_id` and the parent's visibility descriptor. This is the
  follow-up anticipated by emit.py's coverage-caveat docstring.
- **`events/scope.py` stays the single scope mechanism.** `can_see` currently types on
  `InvalidationEvent`; it is widened to the descriptor fields (`visibility`,
  `created_by_user_id`, `shared_with_user_ids`) so both event kinds pass through one
  unchanged function. No second filter is introduced.

**Catalog v1** (now actually implementable): `todo.created`, `todo.completed`,
`grocery.item_added`, `grocery.item_checked`, `habit.checked_in`,
`calendar.event_created`.

Child events inherit the parent's visibility descriptor — a grocery item event carries its
list's visibility, a habit check-in carries its habit's.

Future: `proposal.created` / `proposal.decided` (first additions once agent-proposals
ships), `member.*`.

**Visibility vocabulary note:** this doc previously said "sensitive-scope events are never
delivered to webhooks in v1." There is no `sensitive` visibility in the code —
`core/visibility.py` has `household | personal | members`. Root CLAUDE.md's
"shared / personal / sensitive" vocabulary never reached the schema. The operative rule is
therefore: never deliver a `personal` or `members` event to a subscription whose owner is
not entitled to it under `can_see`.

**Management:** Settings → Integrations → Webhooks (create/list/pause/delete, secret
shown once, delivery log with last N attempts). MCP parity: `list_webhooks` /
`create_webhook` tools (write-scoped) so agents can wire themselves up — flagship demo:
an agent that subscribes itself to `grocery.item_added`.

## Resolved questions — decided 2026-07-20

**1. Where does the `summary` field allowlist live?** → **A central module**
(`webhooks/summaries.py`) maps each event name to an explicit list of permitted field
names; the delivery worker filters every summary through it before signing. Rejected the
original suggestion of a per-domain `webhook_summary()` method: this is the field-leak
surface, and a central table makes "can a budget amount or a personal note body reach a
receiver?" a single-file read instead of a repo-wide grep. A domain cannot widen the
payload by accident.

**2. Deliveries in `audit_log` or their own table?** → **Both, split by volume.** Delivery
attempts and retry state live only in `webhook_deliveries` (frequent, machine-generated,
prunable). Subscription *lifecycle* actions — created, paused, deleted, auto-disabled —
each write one `audit_log` row, because those are human-initiated decisions about where
household data may egress. No `audit_log` row per delivery attempt: that table is indexed
`(household_id, created_at)` for a human-readable Activity page and would be flooded.

**3. Per-subscription filters beyond patterns?** → **No. `event_patterns` is the entire
filter surface in v1.** Deferred to `webhook-002` if demand appears. Noted tension for
whoever picks it up: because payloads are skinny, a receiver *cannot* filter locally on a
field it was never sent, so "only todos assigned to me" otherwise costs an authenticated
REST round-trip per event. Any filter added later must apply strictly **after** `can_see` —
a filter narrows, it can never widen.

**4. HA preset?** → **Docs recipe in `webhook-001`, UI prefill in `webhook-002`.** The
recipe ships with v1 (point an ordinary subscription at `/api/webhook/<id>`, plus sample
automation YAML consuming `trigger.json`) so the delivery worker is validated against a
real third-party receiver before it ships. Explicitly **not** an HA-shaped payload variant:
a second payload shape would break the one-contract property the skinny design buys and
would force the allowlist to be enforced twice. Note HA cannot verify the HMAC — that path
relies on webhook-ID secrecy plus the LAN boundary, which is acceptable under the
self-hosted SSRF policy.

## Still open

- Should `proposal.created` / `proposal.decided` join the catalog as part of `proposal-001`
  itself, rather than waiting for a follow-up? Both builds are migration-bearing and cannot
  run concurrently, so whichever lands second inherits the integration cost either way.
- Egress auditing at the cloud tier: is per-delivery audit needed once third-party egress
  carries compliance weight? Revisit when the managed tier ships.

## Build order — for the `webhook-001` session

**Concurrency:** `webhook-001` adds two tables and `proposal-001` adds one. They must not
run at the same time (root CLAUDE.md → "Tasks that each add migrations must not run
concurrently"). Head at spec time is `0045`. Whichever starts second re-parents its
`down_revision` onto the new head and verifies `alembic heads` returns exactly one.

**Before branching:** the working tree on `main` currently carries this track doc, the
agent-proposals doc, and the root CLAUDE.md MCP-verb principle **uncommitted** — the spec
this build implements is not yet in git history. Land those first, or the branch builds
from files that only exist locally. The PWA/mobile-responsive work in the same tree is a
separate unfiled feature; don't sweep it into a webhook commit. (`feat/pwa-001` is stale —
it diffs as *behind* main and would revert `infra-003`.)

Suggested commit sequence on `feat/webhook-001`, each independently reviewable:

1. **Semantic event layer alone** — `SemanticEvent`, the `session.info` key, publication
   from the existing `after_commit` listener, and `can_see` widened to the descriptor
   fields. Tests: emission, rollback safety, scope parity with the SSL filter. This is the
   structural change and is worth landing readable on its own; everything else stacks on it.
2. **Domain emit calls** — the six catalog events, including the two child-table cases that
   must borrow their parent's `household_id` and visibility.
3. **Migration + models** — `webhook_subscriptions`, `webhook_deliveries`.
4. **Delivery worker** — signing, the central summary allowlist, retries/backoff,
   auto-disable, SSRF policy keyed on `DEPLOYMENT_TIER`.
5. **Settings UI + HA docs recipe.**
6. **Tracking files last**, after the rebase, per the merge protocol.

**Watch for:** the SSRF check must re-resolve at delivery time, not only at subscription
create time, or a hostname that resolves private later defeats it. The self-hosted tier
must keep allowing LAN targets — a regression there kills the HA use case, which is the
main reason this feature exists.

## Feature entries — filed 2026-07-20

Both are in `feature_list.json`, `passes: false`.

- `webhook-001` — semantic event layer (the prerequisite discovered in this thread) +
  subscriptions table + signed delivery worker + scope filtering + settings UI + HA docs
  recipe. **Migration-bearing → must serialize against `proposal-001`,** which also adds a
  table.
- `webhook-002` — MCP management tools + delivery log UI + HA UI preset; per-subscription
  filters if demand appears.
