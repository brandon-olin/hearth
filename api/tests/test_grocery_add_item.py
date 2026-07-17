"""Tests for POST /grocery-lists/{list_id}/items — the single-item append
primitive added for voice-001 (Home Assistant "add milk to the list").

The list-level PATCH replaces the whole items array; a stateless caller (an HA
rest_command, an agent holding a scoped PAT) can't read-merge-write in one
shot. These cover: append doesn't clobber existing items, household scoping
returns None (→ 404), and the PAT scope path for this route resolves to
(grocery, write) so a grocery:write token — and only a write token — reaches it.
"""
import uuid
from decimal import Decimal

from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.pat_scopes import check_scope, resolve_required_scope
from life_dashboard.domains.grocery_lists import service
from life_dashboard.domains.grocery_lists.schemas import (
    GroceryItemAdd,
    GroceryItemData,
    GroceryListCreate,
)


async def _make_household(db) -> tuple[uuid.UUID, uuid.UUID]:
    household = Household(name="Test Household")
    db.add(household)
    await db.flush()
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="x",
        display_name="Test",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(HouseholdMembership(
        household_id=household.id, user_id=user.id, role=MembershipRole.owner,
    ))
    await db.commit()
    return household.id, user.id


async def _make_list(db, household_id, user_id, items=None) -> uuid.UUID:
    created = await service.create_grocery_list(
        db, household_id, user_id,
        GroceryListCreate(name="Groceries", items=items or []),
    )
    return created.id


# ── append behaviour ──────────────────────────────────────────────────────────

async def test_add_item_appends_without_clobbering(db_session):
    hid, uid = await _make_household(db_session)
    list_id = await _make_list(db_session, hid, uid, items=[GroceryItemData(name="eggs")])

    added = await service.add_grocery_item(
        db_session, list_id, hid, GroceryItemAdd(name="milk", quantity=Decimal("2"), unit="L"),
    )

    assert added is not None
    assert added.name == "milk"
    assert added.list_id == list_id

    fetched = await service.get_grocery_list(db_session, list_id, hid)
    names = {i.name for i in fetched.items}
    assert names == {"eggs", "milk"}  # existing item survived the append


async def test_add_item_to_empty_list(db_session):
    hid, uid = await _make_household(db_session)
    list_id = await _make_list(db_session, hid, uid)

    added = await service.add_grocery_item(db_session, list_id, hid, GroceryItemAdd(name="bread"))

    assert added is not None
    fetched = await service.get_grocery_list(db_session, list_id, hid)
    assert [i.name for i in fetched.items] == ["bread"]


# ── household scoping ─────────────────────────────────────────────────────────

async def test_add_item_wrong_household_returns_none(db_session):
    hid, uid = await _make_household(db_session)
    list_id = await _make_list(db_session, hid, uid)
    other_hid, _ = await _make_household(db_session)

    result = await service.add_grocery_item(
        db_session, list_id, other_hid, GroceryItemAdd(name="milk"),
    )

    assert result is None  # router turns this into a 404 — no cross-household writes


async def test_add_item_unknown_list_returns_none(db_session):
    hid, _ = await _make_household(db_session)
    result = await service.add_grocery_item(
        db_session, uuid.uuid4(), hid, GroceryItemAdd(name="milk"),
    )
    assert result is None


def test_add_schema_rejects_recipe_fk_fields():
    # The append route's input schema deliberately omits recipe_id /
    # recipe_ingredient_id so an external caller can't inject a bogus FK UUID
    # (which would trip an IntegrityError → uncaught 500). Pydantic ignores
    # unknown keys by default, so the fields simply don't exist on the model.
    item = GroceryItemAdd(name="milk", recipe_id=uuid.uuid4())  # extra key ignored
    assert not hasattr(item, "recipe_id")
    assert not hasattr(item, "recipe_ingredient_id")


# ── PAT authorization for this route ──────────────────────────────────────────

def test_pat_route_requires_grocery_write():
    # POST to the append endpoint is a write on the grocery domain.
    domain, action = resolve_required_scope("/grocery-lists/abc/items", "POST")
    assert (domain, action) == ("grocery", "write")

    assert check_scope({"grocery": "write"}, domain, action)      # write token reaches it
    assert not check_scope({"grocery": "read"}, domain, action)   # read-only token cannot
    assert not check_scope({"todos": "write"}, domain, action)    # unrelated scope cannot
