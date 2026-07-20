"""Service-layer tests for the workouts-001 refactor.

Covers the feature_list verification steps: the seeded catalog, superset-group
rules (2–5 members, dissolve-lone-member), set round-trip, template
materialization into a session, and the personal/shared scope split. Runs on the
in-memory SQLite engine from conftest's create_all schema, seeding the global
catalog via ``ensure_global_exercises`` (the migration's data step does not run
on the create_all path).
"""
import uuid

import pytest
import pytest_asyncio

from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.domains.workouts import (
    exercises_service,
    sessions_service,
    templates_service,
)
from life_dashboard.domains.workouts.schemas import (
    ExerciseCreate,
    SessionExerciseCreate,
    TemplateExerciseCreate,
    TemplateExerciseUpdate,
    WorkoutSessionCreate,
    WorkoutSetCreate,
    WorkoutTemplateCreate,
)
from life_dashboard.domains.workouts.seed_data import GLOBAL_EXERCISES
from life_dashboard.domains.workouts.superset import SupersetError


@pytest_asyncio.fixture
async def household(db_session):
    """A household with two members (alice=owner, bob=member) and the global
    exercise catalog seeded. Returns the ids the tests need."""
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
    return {"hid": hh.id, "alice": alice.id, "bob": bob.id}


async def _two_exercise_ids(db_session, hid) -> list[uuid.UUID]:
    result = await exercises_service.list_exercises(db_session, hid, limit=5)
    return [e.id for e in result.items[:3]]


# ── Seeded catalog ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_global_catalog_seeded(db_session, household):
    result = await exercises_service.list_exercises(db_session, household["hid"], limit=500)
    assert result.total == len(GLOBAL_EXERCISES) == 63
    # All are global (household_id NULL) and visible to the household.
    assert all(e.is_global and e.household_id is None for e in result.items)


@pytest.mark.asyncio
async def test_ensure_global_exercises_idempotent(db_session, household):
    inserted = await exercises_service.ensure_global_exercises(db_session)
    assert inserted == 0  # already seeded by the fixture
    result = await exercises_service.list_exercises(db_session, household["hid"], limit=500)
    assert result.total == len(GLOBAL_EXERCISES)


# ── Custom exercises ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_custom_exercise_is_idempotent_by_name(db_session, household):
    hid, uid = household["hid"], household["alice"]
    ex1, created1 = await exercises_service.create_exercise(
        db_session, hid, uid, ExerciseCreate(name="Sled Push", tracking_type="distance")
    )
    assert created1 is True and ex1.household_id == hid and ex1.is_global is False
    ex2, created2 = await exercises_service.create_exercise(
        db_session, hid, uid, ExerciseCreate(name="  sled push ")
    )
    assert created2 is False and ex2.id == ex1.id  # deduped by normalized name


@pytest.mark.asyncio
async def test_custom_exercise_not_visible_to_other_household(db_session, household):
    hid, uid = household["hid"], household["alice"]
    ex, _ = await exercises_service.create_exercise(
        db_session, hid, uid, ExerciseCreate(name="Zercher Squat")
    )
    other = await exercises_service.get_exercise(db_session, ex.id, uuid.uuid4())
    assert other is None


# ── Superset rules (template) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_template_superset_two_members_grouped(db_session, household):
    hid, uid = household["hid"], household["alice"]
    ex = await _two_exercise_ids(db_session, hid)
    group = uuid.uuid4()
    template = await templates_service.create_template(
        db_session, hid, uid,
        WorkoutTemplateCreate(
            name="Superset day",
            exercises=[
                TemplateExerciseCreate(exercise_id=ex[0], superset_group_id=group),
                TemplateExerciseCreate(exercise_id=ex[1], superset_group_id=group),
            ],
        ),
    )
    detail = await templates_service.get_template(db_session, template.id, hid, uid)
    groups = [e.superset_group_id for e in detail.exercises]
    assert groups == [group, group]
    assert detail.exercise_count == 2


@pytest.mark.asyncio
async def test_template_superset_rejects_sixth_member(db_session, household):
    hid, uid = household["hid"], household["alice"]
    catalog = (await exercises_service.list_exercises(db_session, hid, limit=10)).items
    group = uuid.uuid4()
    # Build a template with a 5-member superset.
    template = await templates_service.create_template(
        db_session, hid, uid,
        WorkoutTemplateCreate(
            name="Big superset",
            exercises=[
                TemplateExerciseCreate(exercise_id=catalog[i].id, superset_group_id=group)
                for i in range(5)
            ],
        ),
    )
    # Adding a 6th to the same group must be rejected.
    with pytest.raises(SupersetError):
        await templates_service.add_template_exercise(
            db_session, template.id, hid,
            TemplateExerciseCreate(exercise_id=catalog[5].id, superset_group_id=group),
        )


@pytest.mark.asyncio
async def test_template_create_rejects_oversized_group(db_session, household):
    hid, uid = household["hid"], household["alice"]
    catalog = (await exercises_service.list_exercises(db_session, hid, limit=10)).items
    group = uuid.uuid4()
    with pytest.raises(SupersetError):
        await templates_service.create_template(
            db_session, hid, uid,
            WorkoutTemplateCreate(
                name="Too big",
                exercises=[
                    TemplateExerciseCreate(exercise_id=catalog[i].id, superset_group_id=group)
                    for i in range(6)
                ],
            ),
        )


@pytest.mark.asyncio
async def test_removing_from_two_member_group_clears_remaining(db_session, household):
    hid, uid = household["hid"], household["alice"]
    ex = await _two_exercise_ids(db_session, hid)
    group = uuid.uuid4()
    template = await templates_service.create_template(
        db_session, hid, uid,
        WorkoutTemplateCreate(
            name="Pair",
            exercises=[
                TemplateExerciseCreate(exercise_id=ex[0], superset_group_id=group),
                TemplateExerciseCreate(exercise_id=ex[1], superset_group_id=group),
            ],
        ),
    )
    detail = await templates_service.get_template(db_session, template.id, hid, uid)
    await templates_service.remove_template_exercise(
        db_session, template.id, detail.exercises[0].id, hid
    )
    after = await templates_service.get_template(db_session, template.id, hid, uid)
    assert len(after.exercises) == 1
    # The lone survivor's group is cleared — no superset-of-one.
    assert after.exercises[0].superset_group_id is None


@pytest.mark.asyncio
async def test_removing_from_three_member_group_keeps_pair(db_session, household):
    hid, uid = household["hid"], household["alice"]
    catalog = (await exercises_service.list_exercises(db_session, hid, limit=10)).items
    group = uuid.uuid4()
    template = await templates_service.create_template(
        db_session, hid, uid,
        WorkoutTemplateCreate(
            name="Trio",
            exercises=[
                TemplateExerciseCreate(exercise_id=catalog[0].id, superset_group_id=group),
                TemplateExerciseCreate(exercise_id=catalog[1].id, superset_group_id=group),
                TemplateExerciseCreate(exercise_id=catalog[2].id, superset_group_id=group),
            ],
        ),
    )
    detail = await templates_service.get_template(db_session, template.id, hid, uid)
    await templates_service.remove_template_exercise(
        db_session, template.id, detail.exercises[0].id, hid
    )
    after = await templates_service.get_template(db_session, template.id, hid, uid)
    assert len(after.exercises) == 2
    assert {e.superset_group_id for e in after.exercises} == {group}


@pytest.mark.asyncio
async def test_unlink_via_update_clears_group_when_pair(db_session, household):
    hid, uid = household["hid"], household["alice"]
    ex = await _two_exercise_ids(db_session, hid)
    group = uuid.uuid4()
    template = await templates_service.create_template(
        db_session, hid, uid,
        WorkoutTemplateCreate(
            name="Pair2",
            exercises=[
                TemplateExerciseCreate(exercise_id=ex[0], superset_group_id=group),
                TemplateExerciseCreate(exercise_id=ex[1], superset_group_id=group),
            ],
        ),
    )
    detail = await templates_service.get_template(db_session, template.id, hid, uid)
    # Clear one member's group via PATCH — the other should dissolve too.
    await templates_service.update_template_exercise(
        db_session, template.id, detail.exercises[0].id, hid,
        TemplateExerciseUpdate(superset_group_id=None),
    )
    after = await templates_service.get_template(db_session, template.id, hid, uid)
    assert all(e.superset_group_id is None for e in after.exercises)


# ── Sets round-trip ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_warmup_set_and_rpe_round_trip(db_session, household):
    hid, uid = household["hid"], household["alice"]
    ex = await _two_exercise_ids(db_session, hid)
    session = await sessions_service.create_session(
        db_session, hid, uid,
        WorkoutSessionCreate(
            name="Set round-trip",
            exercises=[
                SessionExerciseCreate(
                    exercise_id=ex[0],
                    sets=[
                        WorkoutSetCreate(
                            reps=8, weight=100, weight_unit="lbs", is_warmup=True, rpe=8
                        ),
                        WorkoutSetCreate(
                            reps=5, weight=135, weight_unit="lbs", target_reps=5, rpe=9
                        ),
                    ],
                )
            ],
        ),
    )
    detail = await sessions_service.get_session(db_session, session.id, hid, uid)
    sets = detail.exercises[0].sets
    assert len(sets) == 2
    warm = sets[0]
    assert warm.is_warmup is True and warm.rpe == 8 and warm.reps == 8
    assert float(warm.weight) == 100.0 and warm.weight_unit == "lbs"
    assert sets[1].target_reps == 5 and sets[1].rpe == 9


@pytest.mark.asyncio
async def test_distance_set_round_trip(db_session, household):
    hid, uid = household["hid"], household["alice"]
    running = next(
        e for e in (await exercises_service.list_exercises(db_session, hid, search="Running")).items
    )
    session = await sessions_service.create_session(
        db_session, hid, uid,
        WorkoutSessionCreate(
            name="Cardio",
            exercises=[
                SessionExerciseCreate(
                    exercise_id=running.id,
                    sets=[
                        WorkoutSetCreate(
                            distance_meters=5000, distance_unit="km", duration_seconds=1500
                        )
                    ],
                )
            ],
        ),
    )
    s = (await sessions_service.get_session(db_session, session.id, hid, uid)).exercises[0].sets[0]
    assert float(s.distance_meters) == 5000.0 and s.distance_unit == "km"
    assert s.duration_seconds == 1500


# ── Session from template (materialization) ───────────────────────────────────

@pytest.mark.asyncio
async def test_session_from_template_prepopulates_exercises(db_session, household):
    hid, uid = household["hid"], household["alice"]
    ex = await _two_exercise_ids(db_session, hid)
    template = await templates_service.create_template(
        db_session, hid, uid,
        WorkoutTemplateCreate(
            name="Full body",
            exercises=[
                TemplateExerciseCreate(
                    exercise_id=ex[0], default_sets=3, default_reps=8, default_weight=95
                ),
                TemplateExerciseCreate(exercise_id=ex[1], default_sets=2, default_reps=10),
            ],
        ),
    )
    session = await sessions_service.create_session(
        db_session, hid, uid, WorkoutSessionCreate(template_id=template.id)
    )
    detail = await sessions_service.get_session(db_session, session.id, hid, uid)
    assert detail.template_id == template.id
    assert detail.name == "Full body"  # inherited from the template
    assert len(detail.exercises) == 2
    # session_exercises link back to the template slots via template_exercise_id.
    assert all(se.template_exercise_id is not None for se in detail.exercises)
    # First slot materialized 3 sets with the template's default targets.
    first = detail.exercises[0]
    assert len(first.sets) == 3
    assert first.sets[0].target_reps == 8 and float(first.sets[0].weight) == 95.0


@pytest.mark.asyncio
async def test_session_from_other_household_template_is_rejected(db_session, household):
    hid, uid = household["hid"], household["alice"]
    session = await sessions_service.create_session(
        db_session, hid, uid, WorkoutSessionCreate(template_id=uuid.uuid4())
    )
    assert session is None  # unknown/foreign template → None (router answers 404)


# ── Personal scope ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sessions_are_personal(db_session, household):
    hid, alice, bob = household["hid"], household["alice"], household["bob"]
    ex = await _two_exercise_ids(db_session, hid)
    session = await sessions_service.create_session(
        db_session, hid, alice,
        WorkoutSessionCreate(
            name="Alice's private session",
            exercises=[SessionExerciseCreate(exercise_id=ex[0], sets=[WorkoutSetCreate(reps=5)])],
        ),
    )
    # Bob (same household) cannot see or fetch Alice's session.
    assert await sessions_service.get_session(db_session, session.id, hid, bob) is None
    bob_list = await sessions_service.list_sessions(db_session, hid, bob)
    assert bob_list.total == 0
    alice_list = await sessions_service.list_sessions(db_session, hid, alice)
    assert alice_list.total == 1


@pytest.mark.asyncio
async def test_templates_are_shared_ordering_is_personal(db_session, household):
    hid, alice, bob = household["hid"], household["alice"], household["bob"]
    template = await templates_service.create_template(
        db_session, hid, alice, WorkoutTemplateCreate(name="Shared plan")
    )
    # Bob sees Alice's template (shared), but last_used_at is per-user (None for him).
    bob_view = await templates_service.list_templates(db_session, hid, bob)
    assert bob_view.total == 1 and bob_view.items[0].last_used_at is None
    # Alice logs a session from it → her last_used_at becomes non-null.
    await sessions_service.create_session(
        db_session, hid, alice, WorkoutSessionCreate(template_id=template.id)
    )
    alice_view = await templates_service.list_templates(db_session, hid, alice)
    assert alice_view.items[0].last_used_at is not None
    bob_again = await templates_service.list_templates(db_session, hid, bob)
    assert bob_again.items[0].last_used_at is None  # Alice's use does not leak


# ── Template deletion preserves history ───────────────────────────────────────

@pytest.mark.asyncio
async def test_deleting_template_preserves_session_history(db_session, household):
    hid, uid = household["hid"], household["alice"]
    ex = await _two_exercise_ids(db_session, hid)
    template = await templates_service.create_template(
        db_session, hid, uid,
        WorkoutTemplateCreate(
            name="Doomed",
            exercises=[TemplateExerciseCreate(exercise_id=ex[0], default_sets=2, default_reps=5)],
        ),
    )
    session = await sessions_service.create_session(
        db_session, hid, uid, WorkoutSessionCreate(template_id=template.id)
    )
    assert await templates_service.delete_template(db_session, template.id, hid) is True
    # History survives: session still exists, its sets intact, links nulled.
    detail = await sessions_service.get_session(db_session, session.id, hid, uid)
    assert detail is not None
    assert detail.template_id is None
    assert len(detail.exercises) == 1
    assert detail.exercises[0].template_exercise_id is None
    assert len(detail.exercises[0].sets) == 2
