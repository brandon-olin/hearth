"""First-visit hint endpoints, driven through the ASGI app (onboarding-003).

The service-level behaviour is covered in ``test_onboarding_demo_data.py``.
What only exists at the HTTP layer, and so is only reachable here:

* the ``ValueError`` a bad hint id raises is translated to a **422 carrying the
  valid ids**, not a 500. That message is the only thing an agent gets back, so
  it is contract, not decoration;
* ``GET /households/onboarding/hints`` really is registered — it exists
  precisely so the eight domain pages don't call the row-counting
  ``GET /households/onboarding`` on every visit, and a route that is never
  called through the app is how a broken endpoint ships;
* the two views agree: the light endpoint and the agent-facing status document
  report the same dismissals.

Durability is *not* what these prove — the ``get_current_user`` override hands
every request the same in-memory user, so a write that never reached the
database would still satisfy them. That belongs to
``test_dismiss_hint_persists_to_the_database`` next door, which re-reads the row.
"""
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.core.database import Base, get_db
from life_dashboard.main import app


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as db:
        hh = Household(name="The Olins")
        db.add(hh)
        await db.flush()
        user = User(email="b@x.com", password_hash="x", is_active=True)
        db.add(user)
        await db.flush()
        db.add(
            HouseholdMembership(
                household_id=hh.id, user_id=user.id, role=MembershipRole.owner
            )
        )
        await db.commit()

    user.household_id = hh.id
    user.household_name = hh.name
    user.role = MembershipRole.owner.value

    async def _override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield {"client": client, "maker": maker, "user": user}

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_hint_round_trip(env):
    client = env["client"]

    initial = await client.get("/households/onboarding/hints")
    assert initial.status_code == 200
    assert initial.json()["dismissed_hints"] == []
    # The catalog ships with the response so a client never hard-codes the ids.
    assert "budget" in initial.json()["available_hints"]

    dismissed = await client.post(
        "/households/onboarding/hints/dismiss", json={"hint_id": "budget"}
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["dismissed_hints"] == ["budget"]

    # A separate request — this is what a page reload actually does.
    assert (await client.get("/households/onboarding/hints")).json()[
        "dismissed_hints"
    ] == ["budget"]

    # Settings → Account. Idempotent, so the second press is a no-op, not a 4xx.
    for _ in range(2):
        reset = await client.delete("/households/onboarding/hints")
        assert reset.status_code == 200
        assert reset.json()["dismissed_hints"] == []


@pytest.mark.asyncio
async def test_double_dismiss_does_not_duplicate(env):
    client = env["client"]

    first = await client.post(
        "/households/onboarding/hints/dismiss", json={"hint_id": "habits"}
    )
    second = await client.post(
        "/households/onboarding/hints/dismiss", json={"hint_id": "habits"}
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["dismissed_hints"] == ["habits"]


@pytest.mark.asyncio
async def test_unknown_hint_id_is_422_naming_the_valid_ids(env):
    response = await env["client"].post(
        "/households/onboarding/hints/dismiss", json={"hint_id": "teleporter"}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "teleporter" in detail
    assert "budget" in detail and "todos" in detail


@pytest.mark.asyncio
async def test_status_endpoint_also_reports_hints(env):
    """The agent-facing view carries the same state — see the MCP
    `get_onboarding_status` tool, which reads the same service functions."""
    await env["client"].post(
        "/households/onboarding/hints/dismiss", json={"hint_id": "recipes"}
    )

    status = await env["client"].get("/households/onboarding")

    assert status.status_code == 200
    assert status.json()["dismissed_hints"] == ["recipes"]
    assert status.json()["available_hints"]["recipes"] == "/recipes"


@pytest.mark.asyncio
async def test_dismissing_leaves_other_preferences_alone(env):
    """The wizard flag lives in the same JSON column. Losing it would drop an
    established member back into onboarding."""
    user = env["user"]
    user.preferences = {"onboarding_completed": True, "theme": {"accentId": "blue"}}

    await env["client"].post(
        "/households/onboarding/hints/dismiss", json={"hint_id": "notes"}
    )

    assert user.preferences["onboarding_completed"] is True
    assert user.preferences["theme"] == {"accentId": "blue"}
