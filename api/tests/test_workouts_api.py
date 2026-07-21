"""End-to-end coverage for the workouts HTTP + MCP surface.

Complements test_workouts.py (service layer) by exercising every REST route
through the ASGI app and every MCP tool through its function, so the router
wiring and the agent surface are all actually invoked — not just imported. The
legacy Workout/ExerciseEntry endpoints were retired in workouts-001b; the
exercise/template/session router is now the only /workouts surface.
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
from life_dashboard.mcp.auth import MCPAuthError
from life_dashboard.mcp.server import (
    create_workout_template,
    get_exercise_progress,
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

    # list_exercises
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

    # The legacy /workouts list + /workouts/{id} catch-all were retired
    # (workouts-001b): the bare collection path no longer resolves to anything.
    r = await client.get("/workouts")
    assert r.status_code == 404


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


# ── Progress (workouts-004) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rest_progress_series_and_list(api):
    """The Progress tab's two reads, through the router: the per-exercise
    time-series and the ≥2-sessions list. Both are personal — the service
    filters created_by_user_id (proved at the service layer in
    test_workouts.py); here we prove the routes are wired and shaped right."""
    client = api["client"]
    ex = (await client.get("/workouts/exercises", params={"limit": 3})).json()["items"]
    bench, other = ex[0]["id"], ex[1]["id"]

    async def log(exercise_id, day, sets):
        r = await client.post("/workouts/sessions", json={
            "started_at": f"2026-07-{day:02d}T12:00:00Z",
            "exercises": [{"exercise_id": exercise_id, "sets": sets}],
        })
        assert r.status_code == 201

    await log(bench, 3, [{"reps": 5, "weight": 125}])
    await log(bench, 10, [
        {"reps": 10, "weight": 45, "is_warmup": True},
        {"reps": 8, "weight": 135, "target_reps": 8},
        {"reps": 6, "weight": 135, "target_reps": 8},   # failed set
    ])
    await log(other, 12, [{"reps": 12, "weight": 30}])  # only one session

    r = await client.get(f"/workouts/progress/{bench}")
    assert r.status_code == 200
    body = r.json()
    assert body["exercise"]["id"] == bench
    assert [s["session_date"] for s in body["sessions"]] == ["2026-07-03", "2026-07-10"]
    latest = body["sessions"][-1]["sets"]
    assert len(latest) == 2 and all(s["is_warmup"] is False for s in latest)
    assert any(s["reps"] < s["target_reps"] for s in latest)  # ✗ marker input

    # limit trims to the most recent sessions, still oldest-first.
    r = await client.get(f"/workouts/progress/{bench}", params={"limit": 1})
    assert [s["session_date"] for s in r.json()["sessions"]] == ["2026-07-10"]

    # The list only carries exercises with ≥2 sessions.
    r = await client.get("/workouts/progress")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["exercise_id"] for i in items] == [bench]
    assert items[0]["session_count"] == 2
    assert items[0]["sparkline"] == [125.0, 135.0]
    assert items[0]["is_bodyweight"] is False

    # An unknown exercise is a 404, not an empty series.
    assert (await client.get(f"/workouts/progress/{uuid.uuid4()}")).status_code == 404


@pytest.mark.asyncio
async def test_mcp_get_exercise_progress(api):
    """The agent surface for workouts-004 — resolves an exercise by NAME and
    returns the same personal series the Progress tab charts."""
    client = api["client"]
    ctx = _FakeCtx(api["pat"])
    ex = (await client.get("/workouts/exercises", params={"search": "squat"})).json()["items"][0]

    for day, weight in ((4, 185), (11, 195)):
        r = await client.post("/workouts/sessions", json={
            "started_at": f"2026-07-{day:02d}T12:00:00Z",
            "exercises": [{"exercise_id": ex["id"], "sets": [
                {"reps": 10, "weight": 95, "is_warmup": True},
                {"reps": 5, "weight": weight},
            ]}],
        })
        assert r.status_code == 201

    progress = await get_exercise_progress(ctx, exercise=ex["name"].lower())
    assert progress["exercise"]["id"] == ex["id"]
    assert [s["session_date"] for s in progress["sessions"]] == ["2026-07-04", "2026-07-11"]
    # Warmups never reach the agent either.
    assert [s["weight"] for sess in progress["sessions"] for s in sess["sets"]] == [185.0, 195.0]

    with pytest.raises(MCPAuthError):
        await get_exercise_progress(ctx, exercise="Nonexistent Movement")
