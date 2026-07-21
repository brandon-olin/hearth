"""Coverage for the AI-chat workout tools after the workouts-001b cutover.

The coach's create/list/get/update/delete workout tools used to drive the legacy
Workout/ExerciseEntry service. workouts-001b retired that model, so these tools
now translate the coach's aggregate `metrics` payload into the session/exercise/
set model. These tests exercise `execute_tool` end-to-end on the in-memory SQLite
engine to prove the translation lands correctly and the personal scope holds.
"""
import pytest
import pytest_asyncio

from life_dashboard.ai.tools import execute_tool
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.domains.workouts import exercises_service


@pytest_asyncio.fixture
async def coach_ctx(db_session):
    """A household with alice (owner) + bob (member) and the global catalog
    seeded — mirrors the workouts service tests."""
    hh = Household(name="The Olins")
    db_session.add(hh)
    await db_session.flush()
    alice = User(email="a@x.com", password_hash="x", display_name="Alice", is_active=True)
    bob = User(email="b@x.com", password_hash="x", display_name="Bob", is_active=True)
    db_session.add_all([alice, bob])
    await db_session.flush()
    db_session.add_all([
        HouseholdMembership(household_id=hh.id, user_id=alice.id, role=MembershipRole.owner),
        HouseholdMembership(household_id=hh.id, user_id=bob.id, role=MembershipRole.member),
    ])
    await db_session.commit()
    await exercises_service.ensure_global_exercises(db_session)
    return {"db": db_session, "hid": hh.id, "alice": alice.id, "bob": bob.id}


async def _create(ctx, **inp):
    return await execute_tool(ctx["db"], "create_workout", inp, ctx["hid"], ctx["alice"])


# ── create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_workout_translates_strength_sets(coach_ctx):
    res = await _create(
        coach_ctx,
        workout_date="2026-07-15",
        name="Push Day",
        entries=[{
            "name": "Barbell Bench Press",
            "type": "strength",
            "metrics": {"sets": [
                {"weight_lbs": 135, "reps": 8},
                {"weight_lbs": 145, "reps": 6},
            ]},
        }],
    )
    assert res["ok"] is True
    assert res["date"] == "2026-07-15"  # anchored at noon UTC → same calendar day
    assert res["exercises_created"] == 1

    detail = await execute_tool(
        coach_ctx["db"], "get_workout", {"workout_id": res["id"]},
        coach_ctx["hid"], coach_ctx["alice"],
    )
    assert detail["name"] == "Push Day"
    assert len(detail["exercises"]) == 1
    sets = detail["exercises"][0]["sets"]
    assert len(sets) == 2
    assert sets[0]["reps"] == 8 and sets[0]["weight"] == 135.0
    assert sets[1]["reps"] == 6 and sets[1]["weight"] == 145.0


@pytest.mark.asyncio
async def test_create_workout_translates_cardio(coach_ctx):
    res = await _create(
        coach_ctx,
        workout_date="2026-07-16",
        entries=[{
            "name": "Running",
            "type": "cardio",
            "metrics": {"duration_minutes": 30, "distance_km": 5.0},
        }],
    )
    detail = await execute_tool(
        coach_ctx["db"], "get_workout", {"workout_id": res["id"]},
        coach_ctx["hid"], coach_ctx["alice"],
    )
    s = detail["exercises"][0]["sets"][0]
    assert s["duration_seconds"] == 1800
    assert s["distance_meters"] == 5000.0 and s["distance_unit"] == "km"


@pytest.mark.asyncio
async def test_create_workout_mints_custom_exercise_for_unknown_name(coach_ctx):
    res = await _create(
        coach_ctx,
        workout_date="2026-07-17",
        entries=[{"name": "Zercher Carry", "type": "other"}],
    )
    assert res["exercises_created"] == 1
    # The unknown name is now a visible household-custom exercise.
    listed = await exercises_service.list_exercises(
        coach_ctx["db"], coach_ctx["hid"], search="Zercher"
    )
    assert listed.total == 1 and listed.items[0].is_global is False


# ── list / update / delete ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_update_delete_roundtrip(coach_ctx):
    created = await _create(
        coach_ctx, workout_date="2026-07-18", name="Leg Day",
        entries=[{"name": "Back Squat", "type": "strength",
                  "metrics": {"sets": [{"weight_lbs": 225, "reps": 5}]}}],
    )
    wid = created["id"]

    listed = await execute_tool(
        coach_ctx["db"], "list_workouts",
        {"from_date": "2026-07-01", "to_date": "2026-07-31"},
        coach_ctx["hid"], coach_ctx["alice"],
    )
    assert listed["total"] == 1
    assert listed["workouts"][0]["id"] == wid
    assert listed["workouts"][0]["exercise_count"] == 1

    updated = await execute_tool(
        coach_ctx["db"], "update_workout",
        {"workout_id": wid, "name": "Leg Day (heavy)", "workout_date": "2026-07-19"},
        coach_ctx["hid"], coach_ctx["alice"],
    )
    assert updated["name"] == "Leg Day (heavy)" and updated["date"] == "2026-07-19"

    deleted = await execute_tool(
        coach_ctx["db"], "delete_workout", {"workout_id": wid},
        coach_ctx["hid"], coach_ctx["alice"],
    )
    assert deleted["ok"] is True
    gone = await execute_tool(
        coach_ctx["db"], "get_workout", {"workout_id": wid},
        coach_ctx["hid"], coach_ctx["alice"],
    )
    assert "error" in gone


@pytest.mark.asyncio
async def test_sessions_stay_personal_across_the_coach(coach_ctx):
    """A session logged for alice is invisible to bob through the same tools."""
    created = await _create(
        coach_ctx, workout_date="2026-07-20", name="Private",
        entries=[{"name": "Deadlift", "type": "strength",
                  "metrics": {"sets": [{"weight_lbs": 315, "reps": 3}]}}],
    )
    wid = created["id"]

    bob_get = await execute_tool(
        coach_ctx["db"], "get_workout", {"workout_id": wid},
        coach_ctx["hid"], coach_ctx["bob"],
    )
    assert "error" in bob_get
    bob_list = await execute_tool(
        coach_ctx["db"], "list_workouts", {},
        coach_ctx["hid"], coach_ctx["bob"],
    )
    assert bob_list["total"] == 0
