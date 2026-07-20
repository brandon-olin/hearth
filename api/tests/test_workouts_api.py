"""End-to-end coverage for the workouts-001 HTTP + MCP surface.

Complements test_workouts.py (service layer) by exercising every new REST route
through the ASGI app and every new MCP tool through its function, so the router
wiring, route precedence over the legacy /workouts endpoints, and the agent
surface are all actually invoked — not just imported.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import life_dashboard.mcp.server as mcp_server_module
from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.pat_service import create_token
from life_dashboard.core.database import Base, get_db
from life_dashboard.domains.workouts import exercises_service
from life_dashboard.main import app
from life_dashboard.mcp.server import (
    create_workout_template,
    list_exercises,
    list_workout_templates,
    log_workout_session,
)

WORKOUT_SCOPES = {"workouts": "write"}


class _FakeCtx:
    def __init__(self, raw_token: str):
        headers = {"authorization": f"Bearer {raw_token}"}
        request = type("Req", (), {"headers": headers})()
        self.request_context = type("RC", (), {"request": request})()


@pytest_asyncio.fixture
async def api(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # MCP tools resolve their own session via this factory.
    monkeypatch.setattr(mcp_server_module, "AsyncSessionLocal", maker)

    async with maker() as db:
        hh = Household(name="The Olins")
        db.add(hh)
        await db.flush()
        alice = User(email="a@x.com", password_hash="x", display_name="Alice", is_active=True)
        db.add(alice)
        await db.flush()
        db.add(HouseholdMembership(household_id=hh.id, user_id=alice.id, role=MembershipRole.owner))
        await db.commit()
        await exercises_service.ensure_global_exercises(db)
        _, raw_pat = await create_token(db, alice.id, "workout agent", WORKOUT_SCOPES, None)

    # Attach the runtime attributes get_current_user normally injects.
    alice.household_id = hh.id
    alice.household_name = hh.name
    alice.role = MembershipRole.owner.value

    async def _override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: alice

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield {"client": client, "hid": hh.id, "uid": alice.id, "pat": raw_pat}

    app.dependency_overrides.clear()
    await engine.dispose()


# ── REST endpoints ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rest_exercise_and_template_and_session_flow(api):
    client = api["client"]

    # list_exercises (new route wins over legacy /workouts/{id}).
    r = await client.get("/workouts/exercises", params={"search": "bench"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    # create a custom exercise.
    r = await client.post(
        "/workouts/exercises", json={"name": "Sled Drag", "tracking_type": "distance"}
    )
    assert r.status_code == 201
    custom_id = r.json()["id"]

    # pick two globals to build a template.
    ex = (await client.get("/workouts/exercises", params={"limit": 3})).json()["items"]
    group = str(uuid.uuid4())
    r = await client.post("/workouts/templates", json={
        "name": "Push Day",
        "exercises": [
            {"exercise_id": ex[0]["id"], "superset_group_id": group,
             "default_sets": 3, "default_reps": 8},
            {"exercise_id": ex[1]["id"], "superset_group_id": group},
        ],
    })
    assert r.status_code == 201
    template = r.json()
    tid = template["id"]
    assert template["exercise_count"] == 2
    assert {e["superset_group_id"] for e in template["exercises"]} == {group}

    # GET template detail.
    r = await client.get(f"/workouts/templates/{tid}")
    assert r.status_code == 200 and len(r.json()["exercises"]) == 2

    # add a 3rd exercise to the same superset (ok), then a 4th/5th/6th → 400 on 6th.
    for i in range(2, 5):  # brings group to 5 members
        rr = await client.post(f"/workouts/templates/{tid}/exercises", json={
            "exercise_id": ex[2 % len(ex)]["id"], "superset_group_id": group,
        })
        assert rr.status_code == 201
    r = await client.post(f"/workouts/templates/{tid}/exercises", json={
        "exercise_id": custom_id, "superset_group_id": group,
    })
    assert r.status_code == 400  # 6th member rejected

    # PATCH a template scalar.
    r = await client.patch(f"/workouts/templates/{tid}", json={"description": "chest & tris"})
    assert r.status_code == 200 and r.json()["description"] == "chest & tris"

    # start a session from the template — exercises pre-populated.
    r = await client.post("/workouts/sessions", json={"template_id": tid})
    assert r.status_code == 201
    session = r.json()
    sid = session["id"]
    assert session["template_id"] == tid
    assert len(session["exercises"]) == 5
    assert all(se["template_exercise_id"] for se in session["exercises"])

    # add a set to the first session exercise, with warmup + rpe.
    se_id = session["exercises"][0]["id"]
    r = await client.post(f"/workouts/sessions/{sid}/exercises/{se_id}/sets", json={
        "reps": 8, "weight": 135, "weight_unit": "lbs", "is_warmup": True, "rpe": 8,
    })
    assert r.status_code == 201
    set_id = r.json()["id"]
    assert r.json()["is_warmup"] is True and r.json()["rpe"] == 8

    # PATCH the set.
    r = await client.patch(
        f"/workouts/sessions/{sid}/exercises/{se_id}/sets/{set_id}", json={"reps": 10}
    )
    assert r.status_code == 200 and r.json()["reps"] == 10

    # list sessions (personal).
    r = await client.get("/workouts/sessions")
    assert r.status_code == 200 and r.json()["total"] == 1

    # GET session detail.
    r = await client.get(f"/workouts/sessions/{sid}")
    assert r.status_code == 200

    # DELETE the set, then the session.
    del_set = await client.delete(f"/workouts/sessions/{sid}/exercises/{se_id}/sets/{set_id}")
    assert del_set.status_code == 204
    assert (await client.delete(f"/workouts/sessions/{sid}")).status_code == 204
    assert (await client.get(f"/workouts/sessions/{sid}")).status_code == 404

    # legacy route still works (list old workouts) — precedence preserved.
    r = await client.get("/workouts")
    assert r.status_code == 200 and "items" in r.json()


@pytest.mark.asyncio
async def test_rest_superset_dissolve_on_removal(api):
    client = api["client"]
    ex = (await client.get("/workouts/exercises", params={"limit": 3})).json()["items"]
    group = str(uuid.uuid4())
    tid = (await client.post("/workouts/templates", json={
        "name": "Pair",
        "exercises": [
            {"exercise_id": ex[0]["id"], "superset_group_id": group},
            {"exercise_id": ex[1]["id"], "superset_group_id": group},
        ],
    })).json()["id"]
    detail = (await client.get(f"/workouts/templates/{tid}")).json()
    await client.delete(f"/workouts/templates/{tid}/exercises/{detail['exercises'][0]['id']}")
    after = (await client.get(f"/workouts/templates/{tid}")).json()
    assert len(after["exercises"]) == 1
    assert after["exercises"][0]["superset_group_id"] is None


# ── MCP tools ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_workout_tools(api):
    ctx = _FakeCtx(api["pat"])

    # list_exercises
    ex = await list_exercises(ctx, search="squat")
    assert ex["total"] >= 1

    # create_workout_template by exercise NAMES (unknown name → custom exercise)
    created = await create_workout_template(
        ctx, name="Agent Leg Day",
        exercises=["Back Squat", "Leg Press", "My Custom Move"],
    )
    assert created["name"] == "Agent Leg Day" and created["exercise_count"] == 3

    # list_workout_templates
    templates = await list_workout_templates(ctx)
    assert any(t["name"] == "Agent Leg Day" for t in templates["items"])

    # log_workout_session from that template
    session = await log_workout_session(ctx, template="Agent Leg Day")
    assert session["template_id"] is not None
    assert len(session["exercises"]) == 3
    # the template's last_used_at now reflects this member's use
    templates2 = await list_workout_templates(ctx)
    leg = next(t for t in templates2["items"] if t["name"] == "Agent Leg Day")
    assert leg["last_used_at"] is not None
