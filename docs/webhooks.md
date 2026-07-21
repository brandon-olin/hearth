# Outbound webhooks

Hearth can POST household events to any URL as they happen — a Home Assistant
automation, an n8n flow, a family chat bot, another household's agent. This is
the mirror of the REST/MCP surface: instead of something asking Hearth what
changed, Hearth tells it.

Manage subscriptions under **Settings → Integrations → Webhooks**.

---

## What you receive

Payloads are deliberately skinny — an event name, what it happened to, and a
short display summary. If you need more, fetch the entity back through the REST
API with your own token; that keeps every scope decision in one place.

```json
{
  "delivery_id": "3f7c1e5a-0c2b-4f2e-9f11-9d9a1f4f8c31",
  "event": "todo.completed",
  "entity_type": "todo",
  "entity_id": "8f8b9e64-1b0f-4a3f-9d1c-6b0d2b0a7f21",
  "household_id": "5b2d5c9a-9a1e-4a55-9e2f-2f3f9d4c0a11",
  "occurred_at": "2026-07-21T18:04:11.492817+00:00",
  "summary": { "title": "Take out the bins", "status": "done", "due_date": "2026-07-21" }
}
```

Headers:

| Header | Meaning |
|---|---|
| `X-Hearth-Signature` | `t=<unix seconds>, v1=<hex HMAC-SHA256>` — see below |
| `X-Hearth-Delivery` | The delivery id. Stable across retries — dedupe on this |
| `X-Hearth-Event` | The event name, so you can route without parsing the body |

### Event catalog

`GET /webhooks/events` returns this list at runtime, including the exact summary
fields each event can carry.

| Event | Fires when | Summary fields |
|---|---|---|
| `todo.created` | A to-do is created | `title`, `status`, `priority`, `due_date` |
| `todo.completed` | A to-do is marked done | `title`, `status`, `priority`, `due_date`, `completed_at` |
| `grocery.item_added` | An item is added to a list | `name`, `quantity`, `unit`, `category`, `list_id`, `list_name` |
| `grocery.item_checked` | An item is checked off | same as above |
| `habit.checked_in` | A habit is checked in for a day | `habit_id`, `habit_name`, `scheduled_date`, `completed_at` |
| `calendar.event_created` | A calendar event is created | `title`, `location`, `starts_at`, `ends_at`, `all_day` |
| `journal.session_saved` | A guided journal session is saved to an entry | `mode`, `included_transcript`, `message_count`, `appended_to_existing` |

Subscribe with exact names (`todo.completed`), a domain wildcard (`todo.*`), or
`*` for everything.

**The summary fields above are a hard allowlist**, defined in one file
(`api/src/life_dashboard/webhooks/summaries.py`) and applied to every payload
immediately before signing. A field a domain does not declare there cannot reach
your endpoint, even by accident.

### What you will *not* receive

A subscription is **member-owned**: it delivers only events its owner could see
in the app. Another member's personal to-do, or a `members`-scoped item you were
not shared on, is never delivered — not even as a bare "something changed".
Event patterns narrow that further; they can never widen it.

**No entry text, ever.** `journal.session_saved` tells you that a journaling
session happened and which check-in mode it used — never a word of what was
written. Journal entries are notes, and notes carry personal visibility, so the
event reaches only its own author's subscriptions to begin with. This is also
why there is no MCP tool for journaling: the bus event is the entire agent
surface for that feature, deliberately.

---

## Verifying the signature

Every request carries:

```
X-Hearth-Signature: t=1784660651, v1=6f1b…c93a
```

`v1` is `HMAC-SHA256(secret, "<t>.<raw body>")` in hex. Verify against the **raw
request body**, before any JSON parse or re-serialisation — Hearth signs exact
bytes.

Also check that `t` is recent (5 minutes is a good window). The timestamp is
inside the signed message, so a captured payload cannot be replayed later: its
signature only ever validates near its original `t`, and forging a fresh `t`
requires the secret.

### Python

```python
import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(p.strip().split("=", 1) for p in header.split(",") if "=" in p)
    timestamp, provided = parts.get("t"), parts.get("v1")
    if not timestamp or not provided:
        return False
    if abs(time.time() - int(timestamp)) > tolerance:
        return False  # replay
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(provided, expected)
```

### Node

```js
import crypto from "node:crypto";

export function verify(secret, header, body, tolerance = 300) {
  const parts = Object.fromEntries(
    header.split(",").map((p) => p.trim().split("=")),
  );
  if (!parts.t || !parts.v1) return false;
  if (Math.abs(Date.now() / 1000 - Number(parts.t)) > tolerance) return false;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(`${parts.t}.`)
    .update(body) // Buffer of the RAW body
    .digest("hex");
  return crypto.timingSafeEqual(Buffer.from(parts.v1), Buffer.from(expected));
}
```

The secret is shown **once**, when you create the subscription. It is encrypted
at rest and never returned again — if you lose it, delete the subscription and
create a new one.

> If your install has no `FIELD_ENCRYPTION_KEY` set, creating a subscription
> fails with a 503 rather than storing that secret in plaintext. Generate one
> with `python -c "from cryptography.fernet import Fernet;
> print(Fernet.generate_key().decode())"` and set it in the API environment.

---

## Delivery semantics

- **At least once.** Deliveries are queued in a durable table before any HTTP
  call, so a restart does not lose them. A retry re-sends the same
  `delivery_id` and byte-identical body — dedupe on the id.
- **Timeout 5 seconds.** Acknowledge fast and do the work asynchronously.
- **Any 2xx is success.** The response body is ignored.
- **Retries** back off `30s → 5m → 30m → 2h → 6h`, six attempts in all, then the
  delivery is marked failed.
- **Auto-disable.** A subscription that fails a full unbroken cycle (about nine
  hours with no successful delivery) is switched off and shown as
  *Auto-disabled* in settings, with the last error. Fixing the receiver and
  hitting **Resume** clears the counter.
- **Pausing stops egress immediately**, including for events already queued.

## Where you can point a webhook

| Deployment tier | Policy |
|---|---|
| local / self-hosted | Any target, including LAN and loopback. Pointing at your own Home Assistant box is the whole point. |
| cloud | Public hosts only. Private, loopback, and link-local addresses are refused — at creation *and* re-checked on every delivery, so re-pointing a hostname at internal space later does not work either. |

---

## Recipe: Home Assistant

Home Assistant's webhook trigger cannot verify an HMAC, so that path relies on
the secrecy of the webhook ID plus your LAN boundary. That is acceptable on a
self-hosted install; do not use this shape to expose a receiver to the internet.

**1. Create the automation in Home Assistant** (Settings → Automations → new →
edit in YAML):

```yaml
alias: Hearth — announce completed chores
triggers:
  - trigger: webhook
    webhook_id: hearth-chores-9f3a1c7d       # make this long and random
    allowed_methods: [POST]
    local_only: true                          # LAN only
conditions: []
actions:
  - action: notify.mobile_app_phone
    data:
      title: Chore done
      message: "{{ trigger.json.summary.title }} was completed"
mode: queued
```

**2. Subscribe in Hearth** — Settings → Integrations → Webhooks → *Add webhook*:

- **URL** — `http://homeassistant.local:8123/api/webhook/hearth-chores-9f3a1c7d`
- **Events** — `todo.completed`
- **Label** — `Home Assistant`

Copy the signing secret if you plan to verify it elsewhere; HA itself will not
use it.

**3. Complete a to-do in Hearth.** The notification should arrive within a
second or two. If it does not, check the subscription row in settings: a failing
endpoint shows its consecutive-failure count and, eventually, the auto-disable
reason.

The whole payload is available to templates as `trigger.json`, so
`{{ trigger.json.event }}`, `{{ trigger.json.entity_id }}` and any allowlisted
summary field can drive the automation. To fetch the full entity, call Hearth's
REST API back with a scoped access token (Settings → Integrations → Home
Assistant generates one).
