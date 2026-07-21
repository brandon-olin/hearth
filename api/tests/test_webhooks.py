"""Tests for outbound webhooks (webhook-001).

These exercise the real delivery path against a real HTTP receiver bound to
localhost — signing, retries, and the SSRF policy are all things a mocked
transport would let us get wrong.

Verification steps covered here: signature validation, replay rejection, scope
leak (both personal and members visibility), scope parity (can_see is the only
filter), the central allowlist, retry/backoff/auto-disable, delivery-id
idempotence, both SSRF tiers, subscription-lifecycle auditing with zero rows per
delivery attempt, and the secret being shown exactly once.
"""
import json
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from life_dashboard.audit.models import AuditLog
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.settings import settings
from life_dashboard.core.visibility import VISIBILITY_MEMBERS, VISIBILITY_PERSONAL
from life_dashboard.domains.todos import service as todos_service
from life_dashboard.domains.todos.schemas import TodoCreate, TodoUpdate
from life_dashboard.events.bus import SemanticEvent, bus
from life_dashboard.webhooks import service, signing, ssrf, summaries, worker
from life_dashboard.webhooks.models import WebhookDelivery, WebhookSubscription
from life_dashboard.webhooks.schemas import WebhookSubscriptionCreate, WebhookSubscriptionUpdate

# ── Fixtures and helpers ──────────────────────────────────────────────────────


class _Receiver:
    """A real HTTP endpoint on localhost that records what it was sent."""

    def __init__(self, statuses: list[int] | None = None):
        self.requests: list[dict] = []
        # Status codes to answer with, one per request; the last repeats.
        self.statuses = statuses or [200]
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler's API
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                receiver.requests.append(
                    {"headers": dict(self.headers), "body": body, "received_at": int(time.time())}
                )
                index = min(len(receiver.requests) - 1, len(receiver.statuses) - 1)
                self.send_response(receiver.statuses[index])
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):  # silence stderr noise
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/hook"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def receiver():
    r = _Receiver()
    yield r
    r.close()


@pytest.fixture
def encryption_key(monkeypatch):
    """Field encryption on — a subscription secret must never land in plaintext."""
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def local_tier(monkeypatch):
    """Self-hosted/local: LAN and loopback targets are the intended use."""
    monkeypatch.setattr(settings, "deployment_tier", "local")


@pytest.fixture
def cloud_tier(monkeypatch):
    monkeypatch.setattr(settings, "deployment_tier", "cloud")


async def _count(db, model) -> int:
    """Row count for a model — keeps the assertions below readable."""
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _make_household(db) -> Household:
    household = Household(name="Test Household")
    db.add(household)
    await db.flush()
    return household


async def _make_user(db, household) -> User:
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="x",
        display_name="Test",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        HouseholdMembership(
            household_id=household.id, user_id=user.id, role=MembershipRole.member
        )
    )
    await db.commit()
    user.household_id = household.id
    return user


async def _subscribe(db, household, user, url, patterns=("*",)) -> WebhookSubscription:
    created = await service.create_subscription(
        db,
        household.id,
        user.id,
        WebhookSubscriptionCreate(url=url, event_patterns=list(patterns)),
    )
    return (await db.execute(
        select(WebhookSubscription).where(WebhookSubscription.id == created.id)
    )).scalar_one()


def _event(household_id, **kw) -> SemanticEvent:
    return SemanticEvent(
        household_id=household_id,
        event=kw.get("event", "todo.created"),
        entity_type=kw.get("entity_type", "todo"),
        entity_id=kw.get("entity_id", uuid.uuid4()),
        occurred_at=datetime.now(UTC),
        summary=kw.get("summary", {"title": "Milk"}),
        visibility=kw.get("visibility", "household"),
        created_by_user_id=kw.get("created_by_user_id"),
        shared_with_user_ids=kw.get("shared_with_user_ids", ()),
    )


# ── Signature, replay, tamper ─────────────────────────────────────────────────

def test_signature_verifies_against_the_documented_recipe():
    secret = "shhh"
    body = signing.canonical_body({"event": "todo.completed", "summary": {"title": "Bins"}})
    now = int(time.time())
    header = signing.signature_header(secret, now, body)

    assert header.startswith(f"t={now}, v1=")
    assert signing.verify_signature(secret, header, body, now=now) is True


def test_tampered_body_fails_verification():
    secret = "shhh"
    body = signing.canonical_body({"summary": {"title": "Bins"}})
    now = int(time.time())
    header = signing.signature_header(secret, now, body)

    tampered = signing.canonical_body({"summary": {"title": "Something else"}})
    assert signing.verify_signature(secret, header, tampered, now=now) is False


def test_wrong_secret_fails_verification():
    body = signing.canonical_body({"a": 1})
    now = int(time.time())
    header = signing.signature_header("right", now, body)
    assert signing.verify_signature("wrong", header, body, now=now) is False


def test_replayed_body_with_a_stale_timestamp_is_rejected():
    """The timestamp is inside the signed message, so a captured body cannot be
    re-sent later: its signature only ever validates near its original t."""
    secret = "shhh"
    body = signing.canonical_body({"a": 1})
    signed_at = int(time.time())
    header = signing.signature_header(secret, signed_at, body)

    # Same bytes, same header, replayed an hour later.
    assert signing.verify_signature(secret, header, body, now=signed_at + 3600) is False
    # And re-stamping the header with a fresh t does not help without the secret.
    forged = f"t={signed_at + 3600}, v1={header.split('v1=')[1]}"
    assert signing.verify_signature(secret, forged, body, now=signed_at + 3600) is False


def test_malformed_signature_header_is_rejected():
    body = signing.canonical_body({"a": 1})
    now = int(time.time())
    for header in ("", "garbage", "t=abc, v1=deadbeef", "v1=deadbeef", f"t={now}"):
        assert signing.verify_signature("s", header, body, now=now) is False


# ── End-to-end delivery ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_real_todo_completion_is_delivered_and_verifies(
    db_session, receiver, encryption_key, local_tier
):
    """The flagship path: complete a real todo, dispatch, deliver, verify HMAC."""
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    created = await service.create_subscription(
        db_session,
        household.id,
        user.id,
        WebhookSubscriptionCreate(url=receiver.url, event_patterns=["todo.completed"]),
    )
    secret = created.secret

    queue = bus.subscribe_semantic()
    try:
        todo = await todos_service.create_todo(
            db_session, household.id, user.id, TodoCreate(title="Take out bins")
        )
        await todos_service.update_todo(
            db_session, todo.id, household.id, TodoUpdate(status="done")
        )
        events = [queue.get_nowait() for _ in range(queue.qsize())]
    finally:
        bus.unsubscribe_semantic(queue)

    completed = [e for e in events if e.event == "todo.completed"]
    assert len(completed) == 1

    # todo.created was published too, but the pattern narrows to completions.
    for event in events:
        await service.dispatch_event(db_session, event)

    queued = list((await db_session.execute(select(WebhookDelivery))).scalars().all())
    assert [d.event for d in queued] == ["todo.completed"]

    assert await worker.run_due_deliveries(db_session) == 1

    assert len(receiver.requests) == 1
    sent = receiver.requests[0]
    body = sent["body"]
    payload = json.loads(body)
    assert payload["event"] == "todo.completed"
    assert payload["entity_type"] == "todo"
    assert payload["entity_id"] == str(todo.id)
    assert payload["household_id"] == str(household.id)
    assert payload["summary"]["title"] == "Take out bins"
    assert payload["delivery_id"] == str(queued[0].id)
    assert sent["headers"][signing.DELIVERY_HEADER] == str(queued[0].id)
    assert sent["headers"][signing.EVENT_HEADER] == "todo.completed"

    # The signature verifies against the secret shown at creation.
    assert signing.verify_signature(
        secret, sent["headers"][signing.SIGNATURE_HEADER], body, now=sent["received_at"]
    ) is True

    await db_session.refresh(queued[0])
    assert queued[0].status == "delivered"
    assert queued[0].last_status_code == 200


@pytest.mark.asyncio
async def test_retry_reuses_the_same_delivery_id(db_session, encryption_key, local_tier):
    """A receiver must be able to dedupe: the id and body are stable per delivery."""
    failing_then_ok = _Receiver(statuses=[500, 200])
    try:
        household = await _make_household(db_session)
        user = await _make_user(db_session, household)
        sub = await _subscribe(db_session, household, user, failing_then_ok.url)
        await service.dispatch_event(db_session, _event(household.id))
        delivery = (await db_session.execute(select(WebhookDelivery))).scalar_one()

        assert await worker.attempt_delivery(db_session, delivery, sub) is False
        assert delivery.status == "pending"
        assert delivery.attempt_count == 1

        # Retry the same row — the worker re-sends the stored payload.
        assert await worker.attempt_delivery(db_session, delivery, sub) is True
        assert delivery.status == "delivered"

        assert len(failing_then_ok.requests) == 2
        first, second = failing_then_ok.requests
        assert first["headers"][signing.DELIVERY_HEADER] == str(delivery.id)
        assert second["headers"][signing.DELIVERY_HEADER] == str(delivery.id)
        assert first["body"] == second["body"]  # byte-identical, so dedupe is exact
    finally:
        failing_then_ok.close()


# ── Scope: the critical leak test ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_personal_todo_never_reaches_another_members_subscription(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    member_a = await _make_user(db_session, household)
    member_b = await _make_user(db_session, household)
    # B owns a subscription matching everything.
    await _subscribe(db_session, household, member_b, receiver.url, patterns=["*"])

    queue = bus.subscribe_semantic()
    try:
        await todos_service.create_todo(
            db_session,
            household.id,
            member_a.id,
            TodoCreate(title="A's private errand", visibility=VISIBILITY_PERSONAL),
        )
        events = [queue.get_nowait() for _ in range(queue.qsize())]
    finally:
        bus.unsubscribe_semantic(queue)

    assert [e.event for e in events] == ["todo.created"]
    assert events[0].visibility == VISIBILITY_PERSONAL

    for event in events:
        await service.dispatch_event(db_session, event)

    # Nothing was even queued — B's endpoint learns nothing at all.
    assert await _count(db_session, WebhookDelivery) == 0
    assert await worker.run_due_deliveries(db_session) == 0
    assert receiver.requests == []


@pytest.mark.asyncio
async def test_members_visibility_excludes_a_member_not_shared_with(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    member_a = await _make_user(db_session, household)
    member_b = await _make_user(db_session, household)
    member_c = await _make_user(db_session, household)
    await _subscribe(db_session, household, member_b, receiver.url)

    # Shared with C, not B.
    await service.dispatch_event(
        db_session,
        _event(
            household.id,
            visibility=VISIBILITY_MEMBERS,
            created_by_user_id=member_a.id,
            shared_with_user_ids=(str(member_c.id),),
        ),
    )
    assert await _count(db_session, WebhookDelivery) == 0

    # …and the same event to a subscription C owns does deliver.
    await _subscribe(db_session, household, member_c, receiver.url + "/c")
    await service.dispatch_event(
        db_session,
        _event(
            household.id,
            visibility=VISIBILITY_MEMBERS,
            created_by_user_id=member_a.id,
            shared_with_user_ids=(str(member_c.id),),
        ),
    )
    rows = list((await db_session.execute(select(WebhookDelivery))).scalars().all())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_events_from_another_household_are_never_queued(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    await _subscribe(db_session, household, user, receiver.url)

    other_household = await _make_household(db_session)
    await db_session.commit()
    await service.dispatch_event(db_session, _event(other_household.id))
    assert await _count(db_session, WebhookDelivery) == 0


# ── Filters narrow, never widen ───────────────────────────────────────────────

def test_pattern_matching_forms():
    assert summaries.matches_patterns(["*"], "todo.completed") is True
    assert summaries.matches_patterns(["todo.*"], "todo.completed") is True
    assert summaries.matches_patterns(["todo.*"], "grocery.item_added") is False
    assert summaries.matches_patterns(["todo.completed"], "todo.created") is False
    assert summaries.matches_patterns([], "todo.created") is False


def test_unusable_patterns_are_rejected_with_a_helpful_message():
    with pytest.raises(ValueError) as exc:
        summaries.validate_patterns(["todos.completed"])
    assert "todo.completed" in str(exc.value)  # the error enumerates valid values

    assert summaries.validate_patterns(["todo.*", "todo.*"]) == ["todo.*"]


@pytest.mark.asyncio
async def test_pattern_cannot_widen_past_scope(db_session, receiver, encryption_key, local_tier):
    """'*' still delivers nothing the owner may not see."""
    household = await _make_household(db_session)
    owner = await _make_user(db_session, household)
    stranger = await _make_user(db_session, household)
    await _subscribe(db_session, household, owner, receiver.url, patterns=["*"])

    await service.dispatch_event(
        db_session,
        _event(household.id, visibility=VISIBILITY_PERSONAL, created_by_user_id=stranger.id),
    )
    assert await _count(db_session, WebhookDelivery) == 0


# ── The central allowlist ─────────────────────────────────────────────────────

def test_allowlist_strips_fields_a_domain_did_not_declare():
    summary = {
        "title": "Bins",
        "status": "done",
        "description": "the private long-form notes on this task",
        "assigned_to_user_id": "leaky",
    }
    filtered = summaries.filter_summary("todo.completed", summary)
    assert filtered == {"title": "Bins", "status": "done"}


def test_allowlist_serialises_orm_values():
    from decimal import Decimal

    filtered = summaries.filter_summary(
        "grocery.item_added",
        {
            "name": "Milk",
            "quantity": Decimal("2"),
            "unit": "L",
            "list_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        },
    )
    assert filtered == {
        "name": "Milk",
        "quantity": 2,
        "unit": "L",
        "list_id": "11111111-1111-1111-1111-111111111111",
    }


def test_unknown_event_carries_no_summary_at_all():
    assert summaries.filter_summary("budget.transaction_created", {"amount": 9999}) == {}


@pytest.mark.asyncio
async def test_a_widened_domain_summary_does_not_reach_the_payload(
    db_session, receiver, encryption_key, local_tier
):
    """The proof the allowlist is the gate: a domain adding a field to its
    summary changes nothing on the wire until summaries.py names it."""
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    sub = await _subscribe(db_session, household, user, receiver.url)

    await service.dispatch_event(
        db_session,
        _event(
            household.id,
            event="todo.created",
            summary={"title": "Bins", "secret_field": "household bank PIN"},
        ),
    )
    delivery = (await db_session.execute(select(WebhookDelivery))).scalar_one()
    assert "secret_field" not in delivery.payload["summary"]

    # And even a stored payload that somehow carried it is re-filtered at signing.
    delivery.payload = {**delivery.payload, "summary": {"title": "Bins", "secret_field": "x"}}
    await db_session.commit()
    await worker.attempt_delivery(db_session, delivery, sub)
    sent = json.loads(receiver.requests[0]["body"])
    assert sent["summary"] == {"title": "Bins"}


@pytest.mark.asyncio
async def test_events_outside_the_catalog_are_not_dispatched(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    await _subscribe(db_session, household, user, receiver.url, patterns=["*"])

    await service.dispatch_event(db_session, _event(household.id, event="budget.spent"))
    assert await _count(db_session, WebhookDelivery) == 0


# ── Retries, backoff, auto-disable ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backoff_schedule_then_failed_then_auto_disabled(
    db_session, encryption_key, local_tier
):
    dead = _Receiver(statuses=[500])
    try:
        household = await _make_household(db_session)
        user = await _make_user(db_session, household)
        sub = await _subscribe(db_session, household, user, dead.url)
        await service.dispatch_event(db_session, _event(household.id))
        delivery = (await db_session.execute(select(WebhookDelivery))).scalar_one()

        now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
        expected = [30, 5 * 60, 30 * 60, 2 * 60 * 60, 6 * 60 * 60]
        for step, seconds in enumerate(expected, start=1):
            assert await worker.attempt_delivery(db_session, delivery, sub, now=now) is False
            assert delivery.attempt_count == step
            assert delivery.status == "pending"
            assert delivery.next_attempt_at == now + timedelta(seconds=seconds)
            assert delivery.last_status_code == 500

        # One more attempt exhausts the schedule.
        assert await worker.attempt_delivery(db_session, delivery, sub, now=now) is False
        assert delivery.attempt_count == worker.MAX_ATTEMPTS
        assert delivery.status == "failed"
        assert delivery.next_attempt_at is None

        # A full unbroken cycle auto-disables the subscription, with the reason
        # surfaced for the UI.
        await db_session.refresh(sub)
        assert sub.consecutive_failures == worker.MAX_CONSECUTIVE_FAILURES
        assert sub.active is False
        assert "Auto-disabled" in (sub.disabled_reason or "")

        # Every attempt is recorded on the delivery row.
        assert len(dead.requests) == worker.MAX_ATTEMPTS
    finally:
        dead.close()


@pytest.mark.asyncio
async def test_a_success_resets_the_failure_counter(db_session, encryption_key, local_tier):
    flaky = _Receiver(statuses=[500, 200])
    try:
        household = await _make_household(db_session)
        user = await _make_user(db_session, household)
        sub = await _subscribe(db_session, household, user, flaky.url)
        await service.dispatch_event(db_session, _event(household.id))
        delivery = (await db_session.execute(select(WebhookDelivery))).scalar_one()

        await worker.attempt_delivery(db_session, delivery, sub)
        assert sub.consecutive_failures == 1
        await worker.attempt_delivery(db_session, delivery, sub)
        assert sub.consecutive_failures == 0
        assert sub.last_delivery_at is not None
    finally:
        flaky.close()


@pytest.mark.asyncio
async def test_pausing_a_subscription_stops_already_queued_deliveries(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    sub = await _subscribe(db_session, household, user, receiver.url)
    await service.dispatch_event(db_session, _event(household.id))

    await service.update_subscription(
        db_session, sub.id, household.id, user.id, WebhookSubscriptionUpdate(active=False)
    )
    assert await worker.run_due_deliveries(db_session) == 0
    assert receiver.requests == []

    delivery = (await db_session.execute(select(WebhookDelivery))).scalar_one()
    assert delivery.status == "failed"
    assert delivery.last_error == "subscription is not active"


@pytest.mark.asyncio
async def test_a_paused_subscription_receives_no_new_events(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    sub = await _subscribe(db_session, household, user, receiver.url)
    await service.update_subscription(
        db_session, sub.id, household.id, user.id, WebhookSubscriptionUpdate(active=False)
    )
    await service.dispatch_event(db_session, _event(household.id))
    assert await _count(db_session, WebhookDelivery) == 0


@pytest.mark.asyncio
async def test_resuming_clears_the_auto_disable_state(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    sub = await _subscribe(db_session, household, user, receiver.url)
    await service.record_auto_disable(db_session, sub, "endpoint gone")
    await db_session.commit()

    resumed = await service.update_subscription(
        db_session, sub.id, household.id, user.id, WebhookSubscriptionUpdate(active=True)
    )
    assert resumed.active is True
    assert resumed.consecutive_failures == 0
    assert resumed.disabled_reason is None


# ── SSRF policy ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cloud_tier_rejects_private_loopback_and_link_local(cloud_tier):
    for url in (
        "http://127.0.0.1/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/hook",
        "http://192.168.1.10:8123/api/webhook/abc",
        "http://172.16.4.4/hook",
        "http://[::1]/hook",
        "http://localhost:8123/hook",  # resolves to loopback
    ):
        with pytest.raises(ssrf.WebhookTargetRejected):
            await ssrf.assert_target_allowed(url)


@pytest.mark.asyncio
async def test_malformed_urls_are_rejected_on_every_tier(local_tier):
    for url in ("ftp://example.com/hook", "not-a-url", "https://", "file:///etc/passwd"):
        with pytest.raises(ssrf.WebhookTargetRejected):
            await ssrf.assert_target_allowed(url)


@pytest.mark.asyncio
async def test_self_hosted_tier_allows_lan_targets(monkeypatch):
    """The Home Assistant use case must not regress."""
    monkeypatch.setattr(settings, "deployment_tier", "self_hosted")
    for url in (
        "http://192.168.1.10:8123/api/webhook/hearth",
        "http://homeassistant.local:8123/api/webhook/hearth",
        "http://127.0.0.1:9000/hook",
    ):
        await ssrf.assert_target_allowed(url)  # must not raise


@pytest.mark.asyncio
async def test_cloud_tier_rejects_a_rebound_host_at_delivery_time(
    db_session, receiver, encryption_key, local_tier, monkeypatch
):
    """A target that was allowed at create time is re-checked on every attempt."""
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    sub = await _subscribe(db_session, household, user, "http://localhost:9/hook")
    await service.dispatch_event(db_session, _event(household.id))
    delivery = (await db_session.execute(select(WebhookDelivery))).scalar_one()

    # The install moves to the cloud tier (or the hostname is re-pointed at
    # private space); the next attempt must refuse, not connect.
    monkeypatch.setattr(settings, "deployment_tier", "cloud")
    assert await worker.attempt_delivery(db_session, delivery, sub) is False
    assert "target rejected" in (delivery.last_error or "")
    assert delivery.last_status_code is None


@pytest.mark.asyncio
async def test_cloud_tier_refuses_to_create_a_private_subscription(
    db_session, encryption_key, cloud_tier
):
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    with pytest.raises(ssrf.WebhookTargetRejected):
        await service.create_subscription(
            db_session,
            household.id,
            user.id,
            WebhookSubscriptionCreate(url="http://169.254.169.254/", event_patterns=["*"]),
        )


# ── Secrets ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_secret_is_returned_once_and_never_again(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    created = await service.create_subscription(
        db_session,
        household.id,
        user.id,
        WebhookSubscriptionCreate(url=receiver.url, event_patterns=["*"]),
    )
    assert created.secret

    listed = await service.list_subscriptions(db_session, household.id)
    assert len(listed.items) == 1
    assert not hasattr(listed.items[0], "secret")
    assert "secret" not in listed.items[0].model_dump()

    updated = await service.update_subscription(
        db_session,
        created.id,
        household.id,
        user.id,
        WebhookSubscriptionUpdate(description="Home Assistant"),
    )
    assert "secret" not in updated.model_dump()


@pytest.mark.asyncio
async def test_creation_fails_loudly_without_field_encryption(
    db_session, receiver, local_tier, monkeypatch
):
    """A signing secret cannot be hashed, so plaintext storage is refused."""
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)

    with pytest.raises(service.WebhookEncryptionUnavailable) as exc:
        await service.create_subscription(
            db_session,
            household.id,
            user.id,
            WebhookSubscriptionCreate(url=receiver.url, event_patterns=["*"]),
        )
    assert "FIELD_ENCRYPTION_KEY" in str(exc.value)
    assert await _count(db_session, WebhookSubscription) == 0


@pytest.mark.asyncio
async def test_stored_secret_is_encrypted_at_rest(
    db_session, receiver, encryption_key, local_tier
):
    from sqlalchemy import text

    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    created = await service.create_subscription(
        db_session,
        household.id,
        user.id,
        WebhookSubscriptionCreate(url=receiver.url, event_patterns=["*"]),
    )
    # Read the column raw, bypassing the EncryptedText decrypt-on-read.
    raw = (await db_session.execute(
        text("SELECT secret FROM webhook_subscriptions")
    )).scalar_one()
    assert raw != created.secret
    assert raw.startswith("gAAAA")  # Fernet token prefix


# ── Audit trail ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lifecycle_is_audited_and_delivery_attempts_are_not(
    db_session, encryption_key, local_tier
):
    dead = _Receiver(statuses=[500])
    try:
        household = await _make_household(db_session)
        user = await _make_user(db_session, household)
        sub = await _subscribe(db_session, household, user, dead.url)

        await service.update_subscription(
            db_session, sub.id, household.id, user.id, WebhookSubscriptionUpdate(active=False)
        )
        await service.update_subscription(
            db_session, sub.id, household.id, user.id, WebhookSubscriptionUpdate(active=True)
        )

        # Burn a full backoff cycle so the worker auto-disables it.
        await service.dispatch_event(db_session, _event(household.id))
        delivery = (await db_session.execute(select(WebhookDelivery))).scalar_one()
        for _ in range(worker.MAX_ATTEMPTS):
            await worker.attempt_delivery(db_session, delivery, sub)

        rows = list((await db_session.execute(
            select(AuditLog).where(AuditLog.entity_type == "webhook_subscription")
            .order_by(AuditLog.created_at)
        )).scalars().all())
        actions = [r.action for r in rows]
        assert actions == [
            "webhook_subscription_created",
            "webhook_subscription_paused",
            "webhook_subscription_resumed",
            "webhook_subscription_auto_disabled",
        ]

        # Six delivery attempts happened. NONE of them wrote an audit row —
        # audit_log backs a human-readable Activity page and would be flooded.
        assert delivery.attempt_count == worker.MAX_ATTEMPTS
        assert len(dead.requests) == worker.MAX_ATTEMPTS
        assert (await db_session.execute(
            select(func.count()).select_from(AuditLog)
            .where(AuditLog.entity_type.in_(("webhook_delivery", "webhook_deliveries")))
        )).scalar_one() == 0
        assert (await db_session.execute(
            select(func.count()).select_from(AuditLog)
        )).scalar_one() == len(rows)

        # Deleting audits too.
        await service.delete_subscription(db_session, sub.id, household.id, user.id)
        assert (await db_session.execute(
            select(func.count()).select_from(AuditLog)
            .where(AuditLog.action == "webhook_subscription_deleted")
        )).scalar_one() == 1
    finally:
        dead.close()


@pytest.mark.asyncio
async def test_deleting_a_subscription_removes_its_queued_deliveries(
    db_session, receiver, encryption_key, local_tier
):
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    sub = await _subscribe(db_session, household, user, receiver.url)
    await service.dispatch_event(db_session, _event(household.id))
    assert await _count(db_session, WebhookDelivery) == 1

    await service.delete_subscription(db_session, sub.id, household.id, user.id)
    assert await _count(db_session, WebhookDelivery) == 0


@pytest.mark.asyncio
async def test_one_pass_drains_every_due_delivery(
    db_session, receiver, encryption_key, local_tier
):
    """Several subscriptions on one event all deliver in a single worker pass."""
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    for i in range(3):
        # Distinct URLs — a second active subscription to the same target is
        # refused (see test_duplicate_active_target_is_refused).
        await _subscribe(db_session, household, user, f"{receiver.url}/{i}")

    await service.dispatch_event(db_session, _event(household.id))
    assert await _count(db_session, WebhookDelivery) == 3

    assert await worker.run_due_deliveries(db_session) == 3
    assert len(receiver.requests) == 3
    rows = list((await db_session.execute(select(WebhookDelivery))).scalars().all())
    assert all(r.status == "delivered" for r in rows)
    # Each subscription gets its own delivery id.
    assert len({r.id for r in rows}) == 3


@pytest.mark.asyncio
async def test_duplicate_active_target_is_refused(
    db_session, receiver, encryption_key, local_tier
):
    """A double-submitted create must not leave a second permanent egress channel."""
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    await _subscribe(db_session, household, user, receiver.url)

    with pytest.raises(service.DuplicateWebhookTarget):
        await _subscribe(db_session, household, user, receiver.url, patterns=["todo.*"])
    assert await _count(db_session, WebhookSubscription) == 1

    # A paused subscription does not block re-creating the target.
    sub = (await db_session.execute(select(WebhookSubscription))).scalar_one()
    await service.update_subscription(
        db_session, sub.id, household.id, user.id, WebhookSubscriptionUpdate(active=False)
    )
    await _subscribe(db_session, household, user, receiver.url)
    assert await _count(db_session, WebhookSubscription) == 2


@pytest.mark.asyncio
async def test_auto_disable_reason_fits_its_column(
    db_session, receiver, encryption_key, local_tier
):
    """The reason embeds the last error, which can be long. It must be truncated,
    not blow up the write that is recording a failure (Postgres String(200))."""
    household = await _make_household(db_session)
    user = await _make_user(db_session, household)
    sub = await _subscribe(db_session, household, user, receiver.url)

    await service.record_auto_disable(db_session, sub, "x" * 500)
    await db_session.commit()
    assert sub.active is False
    assert len(sub.disabled_reason) <= 200
    assert sub.disabled_reason.endswith("…")
