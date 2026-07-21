"""Outbound webhooks — Hearth as an event source (webhook-001).

Makes Hearth a peer in other people's automations: when a chore is completed,
POST here. The mirror image of Home Assistant inbound — one bus in the middle,
webhooks out one side, REST calls in the other.

Module map:

  summaries.py  the event catalog AND the single per-event field allowlist —
                the only place that decides what may leave the house.
  signing.py    canonical body bytes + the timestamped HMAC-SHA256 signature,
                including the receiver-side verifier the docs publish.
  ssrf.py       tier-dependent egress policy: cloud refuses private space and
                re-resolves per attempt; self-hosted allows the LAN on purpose.
  models.py     webhook_subscriptions + the durable webhook_deliveries queue.
  service.py    subscription lifecycle (audited) and event → delivery dispatch,
                where scope is enforced before any pattern filter.
  worker.py     the dispatcher and delivery loops: sign, POST, retry, disable.
  router.py     Settings → Integrations → Webhooks, a web-session-only surface.
"""
