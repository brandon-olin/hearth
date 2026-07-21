"""The outbound delivery worker: sign, POST, retry, auto-disable (webhook-001).

Two long-lived tasks, started from the app lifespan:

* **dispatcher** — drains the bus's semantic channel and turns each event into
  durable ``webhook_deliveries`` rows (webhooks/service.dispatch_event). Once a
  row is committed the event survives a restart; before that it does not, which
  is the honest boundary of "at-least-once" here.
* **delivery loop** — polls for due rows and attempts them.

Retry schedule is 30s → 5m → 30m → 2h → 6h, then the delivery is marked failed:
six attempts spread over roughly nine hours. Every failed *attempt* increments
the subscription's consecutive-failure counter and any 2xx resets it, so a
subscription whose endpoint is simply gone auto-disables after one full unbroken
backoff cycle rather than retrying into the void forever. Re-activating it from
the UI clears the counter.

The response body is ignored entirely: 2xx is success, everything else — including
a timeout, a refused connection, or a redirect — is a failure worth retrying.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.database import AsyncSessionLocal
from life_dashboard.events.bus import SemanticEvent, bus
from life_dashboard.webhooks import service, signing, ssrf, summaries
from life_dashboard.webhooks.models import WebhookDelivery, WebhookSubscription

logger = logging.getLogger(__name__)

#: Delay before each retry, in seconds. Index N is the wait after the (N+1)-th
#: failed attempt; running off the end marks the delivery failed.
BACKOFF_SECONDS: tuple[int, ...] = (30, 5 * 60, 30 * 60, 2 * 60 * 60, 6 * 60 * 60)

#: Total attempts per delivery: the first, plus one per backoff step.
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1

#: Consecutive failed attempts (across deliveries) before a subscription is
#: auto-disabled. Equal to MAX_ATTEMPTS so that one delivery exhausting the whole
#: schedule — ~9h of a dead endpoint — is exactly enough, and a receiver that
#: succeeds even once in between never trips it.
MAX_CONSECUTIVE_FAILURES = MAX_ATTEMPTS

#: Per-attempt HTTP timeout. Receivers are expected to acknowledge and process
#: asynchronously; a slow receiver is a failed attempt, not a blocked worker.
REQUEST_TIMEOUT_SECONDS = 5.0

#: How long the delivery loop sleeps when nothing is due.
POLL_INTERVAL_SECONDS = 5.0

#: Rows claimed per poll — bounded so one household's burst cannot starve others.
_BATCH_SIZE = 20

_tasks: list[asyncio.Task] = []


# ── One attempt ───────────────────────────────────────────────────────────────

async def _post(url: str, body: bytes, headers: dict[str, str]) -> httpx.Response:
    """The single outbound HTTP call. Split out so tests can substitute it."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
        return await client.post(url, content=body, headers=headers)


async def attempt_delivery(
    db: AsyncSession,
    delivery: WebhookDelivery,
    subscription: WebhookSubscription,
    *,
    now: datetime | None = None,
) -> bool:
    """Make one signed POST attempt and record the outcome. Commits.

    Returns True if the receiver answered 2xx. The delivery id and body bytes are
    identical on every attempt — only the signature timestamp moves — so a
    receiver can dedupe on ``delivery_id`` and still verify freshness.
    """
    now = now or datetime.now(timezone.utc)

    # Re-filter through the central allowlist immediately before signing. The
    # payload was already filtered at dispatch; doing it again means a row queued
    # by an older build (or a hand-edited one) still cannot carry a field the
    # allowlist does not name today.
    payload = dict(delivery.payload or {})
    payload["summary"] = summaries.filter_summary(delivery.event, payload.get("summary"))
    body = signing.canonical_body(payload)

    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Hearth-Webhooks/1",
        signing.SIGNATURE_HEADER: signing.signature_header(
            subscription.secret, timestamp, body
        ),
        signing.DELIVERY_HEADER: str(delivery.id),
        signing.EVENT_HEADER: delivery.event,
    }

    status_code: int | None = None
    error: str | None = None
    try:
        # Re-resolve the target on every attempt: on the cloud tier a hostname
        # that was public at create time may have been re-pointed at private
        # space since (DNS rebinding).
        await ssrf.assert_target_allowed(subscription.url)
        response = await _post(subscription.url, body, headers)
        status_code = response.status_code
        if not (200 <= response.status_code < 300):
            error = f"HTTP {response.status_code}"
    except ssrf.WebhookTargetRejected as exc:
        error = f"target rejected: {exc}"
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"

    delivery.attempt_count += 1
    delivery.last_attempt_at = now
    delivery.last_status_code = status_code
    delivery.last_error = error

    if error is None:
        delivery.status = "delivered"
        delivery.delivered_at = now
        delivery.next_attempt_at = None
        subscription.consecutive_failures = 0
        subscription.last_delivery_at = now
        await db.commit()
        return True

    if delivery.attempt_count >= MAX_ATTEMPTS:
        delivery.status = "failed"
        delivery.next_attempt_at = None
    else:
        delivery.next_attempt_at = now + timedelta(
            seconds=BACKOFF_SECONDS[delivery.attempt_count - 1]
        )

    subscription.consecutive_failures += 1
    if (
        subscription.active
        and subscription.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
    ):
        await service.record_auto_disable(
            db,
            subscription,
            f"Auto-disabled after {subscription.consecutive_failures} consecutive "
            f"failed delivery attempts. Last error: {error}",
        )
        logger.warning(
            "Auto-disabled webhook subscription %s (%s) after %d consecutive failures",
            subscription.id,
            subscription.url,
            subscription.consecutive_failures,
        )

    await db.commit()
    return False


# ── Queue draining ────────────────────────────────────────────────────────────

async def run_due_deliveries(
    db: AsyncSession, *, now: datetime | None = None, limit: int = _BATCH_SIZE
) -> int:
    """Attempt every pending delivery that is due. Returns how many were tried.

    A delivery whose subscription has since been paused, auto-disabled, or
    deleted is retired rather than attempted — pausing must actually stop egress,
    including for events already queued.
    """
    now = now or datetime.now(timezone.utc)
    rows = list((await db.execute(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status == "pending",
            WebhookDelivery.next_attempt_at.is_not(None),
            WebhookDelivery.next_attempt_at <= now,
        )
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(limit)
    )).scalars().all())
    if not rows:
        return 0

    subs = {
        s.id: s
        for s in (await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.id.in_({r.subscription_id for r in rows})
            )
        )).scalars().all()
    }

    attempted = 0
    for delivery in rows:
        sub = subs.get(delivery.subscription_id)
        if sub is None or not sub.active:
            delivery.status = "failed"
            delivery.next_attempt_at = None
            delivery.last_error = "subscription is not active"
            await db.commit()
            continue
        await attempt_delivery(db, delivery, sub, now=now)
        attempted += 1
    return attempted


# ── Long-lived tasks ──────────────────────────────────────────────────────────

async def _dispatcher_loop() -> None:
    """Turn semantic events into durable delivery rows, forever."""
    queue = bus.subscribe_semantic()
    try:
        while True:
            event: SemanticEvent = await queue.get()
            try:
                async with AsyncSessionLocal() as db:
                    await service.dispatch_event(db, event)
            except Exception:  # noqa: BLE001 — one bad event must not kill the loop
                logger.warning(
                    "Failed to dispatch semantic event %s for %s",
                    event.event,
                    event.entity_id,
                    exc_info=True,
                )
    except asyncio.CancelledError:
        raise
    finally:
        bus.unsubscribe_semantic(queue)


async def _delivery_loop() -> None:
    """Poll the queue table and attempt due deliveries, forever."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                attempted = await run_due_deliveries(db)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a transient DB error must not kill the loop
            logger.warning("Webhook delivery pass failed", exc_info=True)
            attempted = 0
        # A full batch means there is probably more due right now; yield briefly
        # rather than sleeping the whole poll interval.
        await asyncio.sleep(0 if attempted >= _BATCH_SIZE else POLL_INTERVAL_SECONDS)


def start() -> None:
    """Start the dispatcher and delivery tasks (idempotent)."""
    global _tasks
    _tasks = [t for t in _tasks if not t.done()]
    if _tasks:
        return
    _tasks = [
        asyncio.create_task(_dispatcher_loop(), name="webhook-dispatcher"),
        asyncio.create_task(_delivery_loop(), name="webhook-delivery"),
    ]
    logger.info("Webhook worker started")


async def stop() -> None:
    """Cancel the worker tasks and wait for them to unwind."""
    global _tasks
    for task in _tasks:
        task.cancel()
    for task in _tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 — shutdown must not raise
            logger.warning("Webhook worker task ended with an error", exc_info=True)
    _tasks = []
