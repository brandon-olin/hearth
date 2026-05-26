"""
Budget domain — service layer.

All business logic lives here. Routers call these functions; no DB access
happens in routes directly.

Household scoping is enforced on every query. Personal/shared visibility
for transactions is enforced via the scope + owner_user_id columns:
  - shared scope  → all household members can see the transaction
  - private scope → only the owner_user_id can see the transaction

Profile filtering (budget-009):
  - All analytics and category queries accept an optional profile_id.
  - Transaction analytics use COALESCE(txn.profile_id, account.profile_id)
    to resolve the effective analytical profile (budget-011).
"""
import calendar
import csv
import hashlib
import io
import re
import uuid
from datetime import date as date_type, datetime, timezone
from typing import Any

from sqlalchemy import and_, case, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.budget.models import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetProfile,
    BudgetProfileMember,
    BudgetRolloverAmount,
    BudgetTarget,
    BudgetTransaction,
)
from life_dashboard.domains.budget.schemas import (
    BudgetAccountCreate,
    BudgetAccountUpdate,
    BudgetAccountResponse,
    BudgetAnalyticsResponse,
    BudgetCategoryAnalyticsEntry,
    BudgetCategoryCreate,
    BudgetCategoryUpdate,
    BudgetCategoryResponse,
    BudgetCategoryGroupCreate,
    BudgetCategoryGroupUpdate,
    BudgetCategoryGroupResponse,
    BudgetCategoryGroupWithCategories,
    BudgetProfileCreate,
    BudgetProfileUpdate,
    BudgetProfileResponse,
    BudgetProfileMemberAdd,
    BudgetProfileMemberUpdate,
    BudgetProfileMemberResponse,
    BudgetProfitAnalyticsResponse,
    BudgetTargetUpsert,
    BudgetTargetResponse,
    BudgetTargetMonthResponse,
    ReattributeResponse,
    IncomeForecastResponse,
    IncomeForecastSource,
    RecurringGenerateResponse,
    RolloverComputeResponse,
    SeedProfilesResponse,
    BudgetSummaryResponse,
    BudgetTransactionCreate,
    BudgetTransactionUpdate,
    BudgetTransactionResponse,
    BudgetTransactionListResponse,
    BudgetTransactionBulkImportResponse,
    TellerConnectRequest,
    TellerSyncResult,
    TellerSyncAllResult,
    TellerConfigResponse,
)
from life_dashboard.domains.budget.teller_client import teller_client, _teller_account_type
from life_dashboard.core.settings import settings

# Maximum profiles per household on the free tier (Personal + Household = 2).
# Additional profiles (e.g. Business) are a paid-tier feature.
FREE_TIER_MAX_PROFILES = 2


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_dedup_hash(account_id: uuid.UUID, txn_date: Any, amount: float, description: str) -> str:
    """
    SHA-256 of (account_id, date, amount, description) as a hex string.
    Used to detect duplicate imports from CSV/OFX files.
    """
    raw = f"{account_id}|{txn_date}|{amount:.2f}|{description.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _transaction_visible_to(model: type[BudgetTransaction], user_id: uuid.UUID):
    """
    SQLAlchemy WHERE fragment: transactions the given user may see.
      shared scope  → any member of the household can see it
      private scope → only the owner
    Household scoping (household_id filter) must still be applied separately.
    """
    return or_(
        model.scope == "shared",
        model.owner_user_id == user_id,
    )


# ── BudgetProfile ─────────────────────────────────────────────────────────────

async def list_profiles(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[BudgetProfileResponse]:
    """
    Return profiles visible to the given user (i.e. profiles they are a member of).
    """
    stmt = (
        select(BudgetProfile)
        .join(
            BudgetProfileMember,
            (BudgetProfileMember.profile_id == BudgetProfile.id) &
            (BudgetProfileMember.user_id == user_id),
        )
        .where(BudgetProfile.household_id == household_id)
        .order_by(BudgetProfile.sort_order, BudgetProfile.name)
    )
    result = await db.execute(stmt)
    return [BudgetProfileResponse.model_validate(p) for p in result.scalars().all()]


async def get_profile(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
) -> BudgetProfile | None:
    stmt = select(BudgetProfile).where(
        BudgetProfile.id == profile_id,
        BudgetProfile.household_id == household_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_profile_member(
    db: AsyncSession,
    profile_id: uuid.UUID,
    user_id: uuid.UUID,
) -> BudgetProfileMember | None:
    stmt = select(BudgetProfileMember).where(
        BudgetProfileMember.profile_id == profile_id,
        BudgetProfileMember.user_id == user_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _profile_accessible(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Return True if user is a member of this profile within the household."""
    profile = await get_profile(db, profile_id, household_id)
    if profile is None:
        return False
    member = await _get_profile_member(db, profile_id, user_id)
    return member is not None


async def create_profile(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: BudgetProfileCreate,
) -> BudgetProfileResponse:
    """
    Create a new budget profile.

    Business profiles (budgeting_style='profit_tracking') are a paid-tier
    feature. On the free tier, households are limited to FREE_TIER_MAX_PROFILES.
    Returns ValueError if the limit is exceeded.
    """
    # Count existing profiles for the household
    count_stmt = select(func.count()).where(
        BudgetProfile.household_id == household_id
    )
    count_result = await db.execute(count_stmt)
    existing_count = count_result.scalar_one()

    if existing_count >= FREE_TIER_MAX_PROFILES and data.budgeting_style == "profit_tracking":
        raise ValueError(
            "Business profiles are a paid-tier feature. "
            f"Free households can have at most {FREE_TIER_MAX_PROFILES} profiles."
        )

    profile = BudgetProfile(
        household_id=household_id,
        **data.model_dump(),
    )
    db.add(profile)
    await db.flush()

    # Seed current user as owner; add all household members as member
    await _seed_profile_members(db, profile.id, household_id, owner_user_id=user_id)

    await db.commit()
    await db.refresh(profile)
    return BudgetProfileResponse.model_validate(profile)


async def update_profile(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
    data: BudgetProfileUpdate,
) -> BudgetProfileResponse | None:
    profile = await get_profile(db, profile_id, household_id)
    if profile is None:
        return None
    for field in data.model_fields_set:
        setattr(profile, field, getattr(data, field))
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(profile)
    return BudgetProfileResponse.model_validate(profile)


async def delete_profile(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    """
    Delete a profile. Personal and Household (sort_order 1 and 2) are protected.
    Returns False if not found; raises ValueError if it's a protected profile.
    """
    profile = await get_profile(db, profile_id, household_id)
    if profile is None:
        return False
    if profile.name in ("Personal", "Household"):
        raise ValueError(f"The '{profile.name}' profile cannot be deleted.")
    await db.delete(profile)
    await db.commit()
    return True


async def seed_default_profiles(
    db: AsyncSession,
    household_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> SeedProfilesResponse:
    """
    Idempotently create the two default profiles (Personal, Household) for a household.
    Called on household creation or manually via POST /budget/profiles/seed-defaults.
    """
    # Load existing profiles by name
    existing_stmt = select(BudgetProfile).where(BudgetProfile.household_id == household_id)
    existing_result = await db.execute(existing_stmt)
    existing = {p.name: p for p in existing_result.scalars().all()}

    defaults = [
        {"name": "Personal",   "budgeting_style": "zero_based", "sort_order": 1},
        {"name": "Household",  "budgeting_style": "zero_based", "sort_order": 2},
    ]

    profiles_created = 0
    members_seeded = 0
    for defn in defaults:
        if defn["name"] not in existing:
            p = BudgetProfile(household_id=household_id, **defn)
            db.add(p)
            await db.flush()
            existing[defn["name"]] = p
            profiles_created += 1
        m = await _seed_profile_members(db, existing[defn["name"]].id, household_id, owner_user_id)
        members_seeded += m

    await db.commit()
    return SeedProfilesResponse(profiles_created=profiles_created, members_seeded=members_seeded)


async def _seed_profile_members(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> int:
    """
    Seed all household members as profile members.
    The owner_user_id gets the 'owner' role; everyone else gets 'member'.
    Existing memberships are skipped (idempotent).
    Returns the number of new rows inserted.
    """
    from life_dashboard.auth.models import User, HouseholdMembership  # avoid circular import

    # User has no household_id column — household membership is via the join table.
    users_stmt = (
        select(User)
        .join(HouseholdMembership, HouseholdMembership.user_id == User.id)
        .where(HouseholdMembership.household_id == household_id)
    )
    users_result = await db.execute(users_stmt)
    users = users_result.scalars().all()

    # Load existing memberships
    existing_stmt = select(BudgetProfileMember.user_id).where(
        BudgetProfileMember.profile_id == profile_id
    )
    existing_result = await db.execute(existing_stmt)
    existing_user_ids = {r for r in existing_result.scalars().all()}

    inserted = 0
    for u in users:
        if u.id in existing_user_ids:
            continue
        role = "owner" if u.id == owner_user_id else "member"
        db.add(BudgetProfileMember(profile_id=profile_id, user_id=u.id, role=role))
        inserted += 1

    return inserted


# ── Profile member management (budget-014) ────────────────────────────────────

async def list_profile_members(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
) -> list[BudgetProfileMemberResponse]:
    stmt = (
        select(BudgetProfileMember)
        .join(BudgetProfile, BudgetProfileMember.profile_id == BudgetProfile.id)
        .where(
            BudgetProfileMember.profile_id == profile_id,
            BudgetProfile.household_id == household_id,
        )
        .order_by(BudgetProfileMember.created_at)
    )
    result = await db.execute(stmt)
    return [BudgetProfileMemberResponse.model_validate(m) for m in result.scalars().all()]


async def add_profile_member(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
    data: BudgetProfileMemberAdd,
) -> BudgetProfileMemberResponse:
    profile = await get_profile(db, profile_id, household_id)
    if profile is None:
        raise ValueError("Profile not found")

    # Check for duplicate
    existing = await _get_profile_member(db, profile_id, data.user_id)
    if existing is not None:
        existing.role = data.role
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return BudgetProfileMemberResponse.model_validate(existing)

    m = BudgetProfileMember(profile_id=profile_id, user_id=data.user_id, role=data.role)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return BudgetProfileMemberResponse.model_validate(m)


async def update_profile_member(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: BudgetProfileMemberUpdate,
    requesting_user_id: uuid.UUID,
) -> BudgetProfileMemberResponse | None:
    profile = await get_profile(db, profile_id, household_id)
    if profile is None:
        return None
    m = await _get_profile_member(db, profile_id, user_id)
    if m is None:
        return None
    m.role = data.role
    m.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(m)
    return BudgetProfileMemberResponse.model_validate(m)


async def remove_profile_member(
    db: AsyncSession,
    profile_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
) -> bool:
    """
    Remove a member from a profile.
    An owner cannot remove themselves without first transferring ownership.
    """
    m = await _get_profile_member(db, profile_id, user_id)
    if m is None:
        return False
    if user_id == requesting_user_id and m.role == "owner":
        raise ValueError(
            "Profile owners cannot remove themselves. Transfer ownership to another member first."
        )
    await db.delete(m)
    await db.commit()
    return True


# ── BudgetAccount ─────────────────────────────────────────────────────────────

async def _get_personal_profile(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> BudgetProfile | None:
    """Return the Personal profile for a household (for default assignment)."""
    stmt = select(BudgetProfile).where(
        BudgetProfile.household_id == household_id,
        BudgetProfile.name == "Personal",
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_household_profile(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> BudgetProfile | None:
    """Return the Household profile for a household (for default assignment)."""
    stmt = select(BudgetProfile).where(
        BudgetProfile.household_id == household_id,
        BudgetProfile.name == "Household",
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_accounts(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    include_archived: bool = False,
    profile_id: uuid.UUID | None = None,
) -> list[BudgetAccountResponse]:
    """
    Return accounts the user is entitled to see:
      - Their own accounts (any scope)
      - Shared accounts belonging to any household member
    Optionally filtered by profile.
    """
    stmt = select(BudgetAccount).where(
        BudgetAccount.household_id == household_id,
        or_(
            BudgetAccount.owner_user_id == user_id,
            BudgetAccount.scope == "shared",
        ),
    )
    if not include_archived:
        stmt = stmt.where(BudgetAccount.archived_at.is_(None))
    if profile_id is not None:
        stmt = stmt.where(BudgetAccount.profile_id == profile_id)
    stmt = stmt.order_by(BudgetAccount.created_at)
    result = await db.execute(stmt)
    return [BudgetAccountResponse.model_validate(a) for a in result.scalars().all()]


async def get_account(
    db: AsyncSession,
    account_id: uuid.UUID,
    household_id: uuid.UUID,
) -> BudgetAccount | None:
    stmt = select(BudgetAccount).where(
        BudgetAccount.id == account_id,
        BudgetAccount.household_id == household_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_account(
    db: AsyncSession,
    household_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    data: BudgetAccountCreate,
) -> BudgetAccountResponse:
    # Resolve profile: use supplied profile_id, or default based on account scope
    profile_id = data.profile_id
    if profile_id is None:
        if data.scope == "shared":
            p = await _get_household_profile(db, household_id)
        else:
            p = await _get_personal_profile(db, household_id)
        if p is not None:
            profile_id = p.id

    if profile_id is None:
        raise ValueError("No profile found for this household. Run seed-defaults first.")

    dump = data.model_dump(exclude={"profile_id"})
    account = BudgetAccount(
        household_id=household_id,
        owner_user_id=owner_user_id,
        profile_id=profile_id,
        **dump,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return BudgetAccountResponse.model_validate(account)


async def update_account(
    db: AsyncSession,
    account_id: uuid.UUID,
    household_id: uuid.UUID,
    data: BudgetAccountUpdate,
) -> BudgetAccountResponse | None:
    account = await get_account(db, account_id, household_id)
    if account is None:
        return None
    for field in data.model_fields_set:
        setattr(account, field, getattr(data, field))
    # budget-017: auto-stamp balance_updated_at whenever current_balance is set
    if "current_balance" in data.model_fields_set:
        account.balance_updated_at = datetime.now(timezone.utc)
    account.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(account)
    return BudgetAccountResponse.model_validate(account)


async def delete_account(
    db: AsyncSession,
    account_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    account = await get_account(db, account_id, household_id)
    if account is None:
        return False
    await db.delete(account)
    await db.commit()
    return True


# ── BudgetCategory ────────────────────────────────────────────────────────────

async def list_categories(
    db: AsyncSession,
    household_id: uuid.UUID,
    include_archived: bool = False,
    profile_id: uuid.UUID | None = None,
) -> list[BudgetCategoryResponse]:
    stmt = select(BudgetCategory).where(BudgetCategory.household_id == household_id)
    if not include_archived:
        stmt = stmt.where(BudgetCategory.archived_at.is_(None))
    if profile_id is not None:
        stmt = stmt.where(BudgetCategory.profile_id == profile_id)
    stmt = stmt.order_by(BudgetCategory.name)  # alphabetical for pickers / dropdowns
    result = await db.execute(stmt)
    return [BudgetCategoryResponse.model_validate(c) for c in result.scalars().all()]


async def get_category(
    db: AsyncSession,
    category_id: uuid.UUID,
    household_id: uuid.UUID,
) -> BudgetCategory | None:
    stmt = select(BudgetCategory).where(
        BudgetCategory.id == category_id,
        BudgetCategory.household_id == household_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_category(
    db: AsyncSession,
    household_id: uuid.UUID,
    data: BudgetCategoryCreate,
) -> BudgetCategoryResponse:
    # Resolve profile
    profile_id = data.profile_id
    if profile_id is None:
        if data.default_scope == "shared":
            p = await _get_household_profile(db, household_id)
        else:
            p = await _get_personal_profile(db, household_id)
        if p is not None:
            profile_id = p.id
    if profile_id is None:
        raise ValueError("No profile found for this household. Run seed-defaults first.")

    dump = data.model_dump(exclude={"profile_id"})

    # Auto-apply icon/color from CATEGORY_DEFAULTS for well-known category names
    # so manually-created categories pick up sensible defaults without the caller
    # having to know about them.
    cat_defs = CATEGORY_DEFAULTS.get(data.name, {})
    if not dump.get("icon") and cat_defs.get("icon"):
        dump["icon"] = cat_defs["icon"]
    if not dump.get("color") and cat_defs.get("color"):
        dump["color"] = cat_defs["color"]

    category = BudgetCategory(
        household_id=household_id,
        profile_id=profile_id,
        **dump,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return BudgetCategoryResponse.model_validate(category)


async def update_category(
    db: AsyncSession,
    category_id: uuid.UUID,
    household_id: uuid.UUID,
    data: BudgetCategoryUpdate,
) -> BudgetCategoryResponse | None:
    category = await get_category(db, category_id, household_id)
    if category is None:
        return None
    for field in data.model_fields_set:
        setattr(category, field, getattr(data, field))
    category.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(category)
    return BudgetCategoryResponse.model_validate(category)


async def delete_category(
    db: AsyncSession,
    category_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    category = await get_category(db, category_id, household_id)
    if category is None:
        return False
    await db.delete(category)
    await db.commit()
    return True


# ── BudgetCategoryGroup ───────────────────────────────────────────────────────

# Per-category icon and color defaults used when seeding new categories.
# Values match the DEFAULT_CATEGORIES list in the frontend categories page.
CATEGORY_DEFAULTS: dict[str, dict] = {
    "Income":        {"icon": "💰", "color": "#22c55e"},
    "Housing":       {"icon": "🏠", "color": "#64748b"},
    "Utilities":     {"icon": "💡", "color": "#eab308"},
    "Groceries":     {"icon": "🛒", "color": "#3b82f6"},
    "Dining":        {"icon": "🍽️", "color": "#f97316"},
    "Transportation":{"icon": "🚗", "color": "#8b5cf6"},
    "Travel":        {"icon": "✈️", "color": "#14b8a6"},
    "Subscriptions": {"icon": "📱", "color": "#a3e635"},
    "Shopping":      {"icon": "🛍️", "color": "#0ea5e9"},
    "Healthcare":    {"icon": "🏥", "color": "#ef4444"},
    "Insurance":     {"icon": "🛡️", "color": "#f43f5e"},
    "Personal Care": {"icon": "💆", "color": "#ec4899"},
    "Education":     {"icon": "📚", "color": "#6366f1"},
    "Savings":       {"icon": "📈", "color": "#22c55e"},
    "Household":     {"icon": "🛋️", "color": "#b45309"},
    "Gifts":         {"icon": "🎁", "color": "#db2777"},
    "Entertainment": {"icon": "🎬", "color": "#a855f7"},
    "Gaming":        {"icon": "🎮", "color": "#06b6d4"},
    "Vices":         {"icon": "🍷", "color": "#92400e"},
}

# Default group definitions — names and sort orders match the YNAB-inspired
# taxonomy defined in budget-005. The seeding endpoint creates these for the
# household and assigns matching categories by name.

DEFAULT_GROUPS: list[dict] = [
    {"name": "Fixed Monthly",            "sort_order": 1, "is_income": False,
     "category_names": ["Housing", "Utilities", "Insurance", "Subscriptions"]},
    {"name": "Everyday Spending",        "sort_order": 2, "is_income": False,
     "category_names": ["Groceries", "Dining", "Transportation", "Personal Care"]},
    {"name": "Irregular / True Expenses","sort_order": 3, "is_income": False,
     "category_names": ["Household", "Healthcare", "Travel", "Gifts", "Education", "Shopping"]},
    {"name": "Savings & Goals",          "sort_order": 4, "is_income": False,
     "category_names": ["Savings"]},
    {"name": "Just for Fun",             "sort_order": 5, "is_income": False,
     "category_names": ["Entertainment", "Gaming", "Vices"]},
    {"name": "Income",                   "sort_order": 6, "is_income": True,
     "category_names": ["Income"]},
]

# Default groups for profit_tracking (Business) profiles (budget-012)
DEFAULT_BUSINESS_GROUPS: list[dict] = [
    {"name": "Revenue",            "sort_order": 1, "is_income": True,  "category_names": []},
    {"name": "Cost of Goods",      "sort_order": 2, "is_income": False, "category_names": []},
    {"name": "Operating Expenses", "sort_order": 3, "is_income": False, "category_names": []},
    {"name": "Owner's Pay",        "sort_order": 4, "is_income": False, "category_names": []},
]


async def list_groups(
    db: AsyncSession,
    household_id: uuid.UUID,
    profile_id: uuid.UUID | None = None,
) -> list[BudgetCategoryGroupResponse]:
    stmt = (
        select(BudgetCategoryGroup)
        .where(BudgetCategoryGroup.household_id == household_id)
    )
    if profile_id is not None:
        stmt = stmt.where(BudgetCategoryGroup.profile_id == profile_id)
    stmt = stmt.order_by(BudgetCategoryGroup.sort_order, BudgetCategoryGroup.name)
    result = await db.execute(stmt)
    return [BudgetCategoryGroupResponse.model_validate(g) for g in result.scalars().all()]


async def get_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    household_id: uuid.UUID,
) -> BudgetCategoryGroup | None:
    stmt = select(BudgetCategoryGroup).where(
        BudgetCategoryGroup.id == group_id,
        BudgetCategoryGroup.household_id == household_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_group(
    db: AsyncSession,
    household_id: uuid.UUID,
    data: BudgetCategoryGroupCreate,
) -> BudgetCategoryGroupResponse:
    # Resolve profile — groups default to Household profile
    profile_id = data.profile_id
    if profile_id is None:
        p = await _get_household_profile(db, household_id)
        if p is not None:
            profile_id = p.id
    if profile_id is None:
        raise ValueError("No profile found for this household. Run seed-defaults first.")

    dump = data.model_dump(exclude={"profile_id"})
    group = BudgetCategoryGroup(household_id=household_id, profile_id=profile_id, **dump)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return BudgetCategoryGroupResponse.model_validate(group)


async def update_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    household_id: uuid.UUID,
    data: BudgetCategoryGroupUpdate,
) -> BudgetCategoryGroupResponse | None:
    group = await get_group(db, group_id, household_id)
    if group is None:
        return None
    for field in data.model_fields_set:
        setattr(group, field, getattr(data, field))
    group.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(group)
    return BudgetCategoryGroupResponse.model_validate(group)


async def delete_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    group = await get_group(db, group_id, household_id)
    if group is None:
        return False
    await db.delete(group)
    await db.commit()
    return True


async def list_categories_grouped(
    db: AsyncSession,
    household_id: uuid.UUID,
    include_archived: bool = False,
    profile_id: uuid.UUID | None = None,
) -> list[BudgetCategoryGroupWithCategories]:
    """
    Return all categories nested under their groups, ordered by group sort_order.
    Categories with no group_id appear in a trailing implicit "Other" bucket.
    Optionally filtered to a specific profile.
    """
    # Load groups ordered by sort_order
    grp_stmt = (
        select(BudgetCategoryGroup)
        .where(BudgetCategoryGroup.household_id == household_id)
    )
    if profile_id is not None:
        grp_stmt = grp_stmt.where(BudgetCategoryGroup.profile_id == profile_id)
    grp_stmt = grp_stmt.order_by(BudgetCategoryGroup.sort_order, BudgetCategoryGroup.name)
    grp_result = await db.execute(grp_stmt)
    groups = grp_result.scalars().all()

    # Load all categories for the household (filtered by profile if given)
    cat_stmt = (
        select(BudgetCategory)
        .where(BudgetCategory.household_id == household_id)
    )
    if not include_archived:
        cat_stmt = cat_stmt.where(BudgetCategory.archived_at.is_(None))
    if profile_id is not None:
        cat_stmt = cat_stmt.where(BudgetCategory.profile_id == profile_id)
    cat_stmt = cat_stmt.order_by(BudgetCategory.sort_order, BudgetCategory.name)
    cat_result = await db.execute(cat_stmt)
    all_cats = cat_result.scalars().all()

    # Build lookup: group_id → [categories]
    from collections import defaultdict
    by_group: dict[uuid.UUID | None, list] = defaultdict(list)
    for cat in all_cats:
        by_group[cat.group_id].append(BudgetCategoryResponse.model_validate(cat))

    # Build result in group order
    out: list[BudgetCategoryGroupWithCategories] = []
    for grp in groups:
        out.append(BudgetCategoryGroupWithCategories(
            id=grp.id,
            name=grp.name,
            sort_order=grp.sort_order,
            is_income=grp.is_income,
            categories=by_group.get(grp.id, []),
        ))

    # Append implicit "Other" for ungrouped categories
    ungrouped = by_group.get(None, [])
    if ungrouped:
        out.append(BudgetCategoryGroupWithCategories(
            id=None,
            name="Other",
            sort_order=9999,
            is_income=False,
            categories=ungrouped,
        ))

    return out


async def seed_default_groups(
    db: AsyncSession,
    household_id: uuid.UUID,
    profile_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """
    Create the default category groups for a household and assign matching
    categories by name. Idempotent: skips groups that already exist (by name).

    If profile_id is None, uses the Household profile by default.
    For profit_tracking profiles, seeds Business groups instead.

    Returns {"groups_created": N, "categories_assigned": M}
    """
    # Resolve profile
    if profile_id is None:
        p = await _get_household_profile(db, household_id)
        profile_id = p.id if p else None

    # Determine which group template to use
    group_template = DEFAULT_GROUPS
    if profile_id is not None:
        prof = await get_profile(db, profile_id, household_id)
        if prof and prof.budgeting_style == "profit_tracking":
            group_template = DEFAULT_BUSINESS_GROUPS

    # Load existing group names (scoped to the profile if given)
    existing_grp_stmt = select(BudgetCategoryGroup).where(
        BudgetCategoryGroup.household_id == household_id
    )
    if profile_id is not None:
        existing_grp_stmt = existing_grp_stmt.where(
            BudgetCategoryGroup.profile_id == profile_id
        )
    existing_grp_result = await db.execute(existing_grp_stmt)
    existing_groups = {g.name: g for g in existing_grp_result.scalars().all()}

    # Load existing categories by name for assignment — search ALL profiles in the
    # household so we don't create duplicates when categories belong to a different
    # profile than the one being seeded (e.g. Personal categories while seeding Household groups).
    existing_cat_stmt = select(BudgetCategory).where(
        BudgetCategory.household_id == household_id,
        BudgetCategory.archived_at.is_(None),
    )
    existing_cat_result = await db.execute(existing_cat_stmt)
    cats_by_name = {c.name.lower(): c for c in existing_cat_result.scalars().all()}

    groups_created = 0
    categories_assigned = 0

    for defn in group_template:
        grp_name = defn["name"]
        if grp_name not in existing_groups:
            grp = BudgetCategoryGroup(
                household_id=household_id,
                profile_id=profile_id,
                name=grp_name,
                sort_order=defn["sort_order"],
                is_income=defn.get("is_income", False),
            )
            db.add(grp)
            await db.flush()  # get grp.id before using it below
            existing_groups[grp_name] = grp
            groups_created += 1
        else:
            # Sync is_income flag from template in case it was created before the flag existed.
            grp_obj = existing_groups[grp_name]
            expected_is_income = defn.get("is_income", False)
            if grp_obj.is_income != expected_is_income:
                grp_obj.is_income = expected_is_income

        grp_obj = existing_groups[grp_name]
        for cat_name in defn.get("category_names", []):
            cat = cats_by_name.get(cat_name.lower())
            if cat is None:
                # Category doesn't exist yet — create it and assign to this group.
                # Apply icon/color defaults if known for this category name.
                cat_defs = CATEGORY_DEFAULTS.get(cat_name, {})
                cat = BudgetCategory(
                    household_id=household_id,
                    profile_id=profile_id,
                    name=cat_name,
                    default_scope="private",
                    group_id=grp_obj.id,
                    icon=cat_defs.get("icon"),
                    color=cat_defs.get("color"),
                )
                db.add(cat)
                cats_by_name[cat_name.lower()] = cat
                categories_assigned += 1
            else:
                # Category exists — back-fill icon/color if currently unset.
                cat_defs = CATEGORY_DEFAULTS.get(cat_name, {})
                changed = False
                if cat.group_id is None:
                    cat.group_id = grp_obj.id
                    changed = True
                if cat.icon is None and cat_defs.get("icon"):
                    cat.icon = cat_defs["icon"]
                    changed = True
                if cat.color is None and cat_defs.get("color"):
                    cat.color = cat_defs["color"]
                    changed = True
                if changed:
                    cat.updated_at = datetime.now(timezone.utc)
                    categories_assigned += 1

    await db.commit()
    return {"groups_created": groups_created, "categories_assigned": categories_assigned}


async def auto_budget_fixed_categories(
    db: AsyncSession,
    household_id: uuid.UUID,
    profile_id: uuid.UUID | None = None,
    months: int = 3,
    group_name: str = "Fixed Monthly",
) -> list[dict]:
    """
    Compute the average monthly spending for every category in the named group
    over the last N *full* calendar months (current partial month excluded) and
    write that average to default_monthly_amount.

    Categories with zero recorded transactions in the sample window are skipped.
    Categories that already have a target are *overwritten* so users can refresh
    the estimate as their spending changes.

    Returns a list of {category_id, name, old_amount, new_amount, months_sampled}
    for every category that was updated.
    """
    import calendar as _cal
    from datetime import date as _date

    today = _date.today()

    # Build (year, month) tuples for the last N full months, newest first.
    # Example: if today is May 21 and months=3 → [(2026,4), (2026,3), (2026,2)]
    periods: list[tuple[int, int]] = []
    y, m = today.year, today.month - 1
    for _ in range(months):
        if m <= 0:
            m += 12
            y -= 1
        periods.append((y, m))
        m -= 1

    if not periods:
        return []

    # Find the target group
    grp_stmt = select(BudgetCategoryGroup).where(
        BudgetCategoryGroup.household_id == household_id,
        BudgetCategoryGroup.name == group_name,
    )
    if profile_id is not None:
        grp_stmt = grp_stmt.where(BudgetCategoryGroup.profile_id == profile_id)
    grp_result = await db.execute(grp_stmt)
    group = grp_result.scalar_one_or_none()
    if group is None:
        return []

    # Load all active categories in that group
    cat_stmt = select(BudgetCategory).where(
        BudgetCategory.household_id == household_id,
        BudgetCategory.group_id == group.id,
        BudgetCategory.archived_at.is_(None),
    )
    cat_result = await db.execute(cat_stmt)
    categories = cat_result.scalars().all()
    if not categories:
        return []

    # Accumulate monthly expense totals per category
    period_totals: dict[uuid.UUID, list[float]] = {cat.id: [] for cat in categories}

    for yr, mo in periods:
        _, last_day = _cal.monthrange(yr, mo)
        from datetime import date as _d2
        date_from = _d2(yr, mo, 1)
        date_to   = _d2(yr, mo, last_day)

        for cat in categories:
            stmt = select(func.sum(BudgetTransaction.amount)).where(
                BudgetTransaction.household_id == household_id,
                BudgetTransaction.category_id == cat.id,
                BudgetTransaction.date >= date_from,
                BudgetTransaction.date <= date_to,
                BudgetTransaction.amount < 0,          # expenses only (negative = spend)
                BudgetTransaction.is_transfer == False,  # noqa: E712
            )
            result = await db.execute(stmt)
            total = result.scalar_one_or_none()
            if total is not None and total != 0:
                period_totals[cat.id].append(abs(float(total)))

    # Compute averages and persist
    updated: list[dict] = []
    for cat in categories:
        samples = period_totals[cat.id]
        if not samples:
            continue  # no data in the window — leave untouched
        avg = round(sum(samples) / len(samples), 2)
        old = float(cat.default_monthly_amount) if cat.default_monthly_amount is not None else None
        cat.default_monthly_amount = avg
        cat.updated_at = datetime.now(timezone.utc)
        updated.append({
            "category_id": str(cat.id),
            "name": cat.name,
            "old_amount": old,
            "new_amount": avg,
            "months_sampled": len(samples),
        })

    if updated:
        await db.commit()
    return updated


# ── BudgetTarget ──────────────────────────────────────────────────────────────

async def upsert_target(
    db: AsyncSession,
    household_id: uuid.UUID,
    data: BudgetTargetUpsert,
) -> BudgetTargetResponse | None:
    """
    Upsert a per-month budget target for a category.

    If data.amount is None, the override row is deleted (the category then falls
    back to its default_monthly_amount).  Returns None when the row was deleted.

    The category must belong to the household; 404 is the caller's responsibility.
    """
    # Verify category ownership
    cat_stmt = select(BudgetCategory).where(
        BudgetCategory.id == data.category_id,
        BudgetCategory.household_id == household_id,
    )
    cat_result = await db.execute(cat_stmt)
    cat = cat_result.scalar_one_or_none()
    if cat is None:
        return None  # caller should raise 404

    if data.amount is None:
        # Delete the override row (if it exists)
        del_stmt = delete(BudgetTarget).where(
            BudgetTarget.category_id == data.category_id,
            BudgetTarget.year == data.year,
            BudgetTarget.month == data.month,
        )
        await db.execute(del_stmt)
        await db.commit()
        return None

    # Upsert: load existing row or create new one
    existing_stmt = select(BudgetTarget).where(
        BudgetTarget.category_id == data.category_id,
        BudgetTarget.year == data.year,
        BudgetTarget.month == data.month,
    )
    existing_result = await db.execute(existing_stmt)
    target = existing_result.scalar_one_or_none()

    if target is None:
        target = BudgetTarget(
            household_id=household_id,
            profile_id=cat.profile_id,
            category_id=data.category_id,
            year=data.year,
            month=data.month,
            amount=data.amount,
        )
        db.add(target)
    else:
        target.amount = data.amount
        target.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(target)
    return BudgetTargetResponse.model_validate(target)


async def get_effective_targets(
    db: AsyncSession,
    household_id: uuid.UUID,
    year: int,
    month: int,
    profile_id: uuid.UUID | None = None,
) -> BudgetTargetMonthResponse:
    """
    Return the effective budget target for every category in the household for
    the given month.

    Resolution: per-month override → default_monthly_amount → None (no target).
    Returns a map of category_id (str) → effective amount (float | None).
    Categories with no target set (neither override nor default) are included
    with amount=None.
    """
    # Load all categories
    cat_stmt = select(BudgetCategory).where(
        BudgetCategory.household_id == household_id,
        BudgetCategory.archived_at.is_(None),
    )
    if profile_id is not None:
        cat_stmt = cat_stmt.where(BudgetCategory.profile_id == profile_id)
    cat_result = await db.execute(cat_stmt)
    categories = cat_result.scalars().all()

    # Load per-month overrides
    override_stmt = select(BudgetTarget).where(
        BudgetTarget.household_id == household_id,
        BudgetTarget.year == year,
        BudgetTarget.month == month,
    )
    if profile_id is not None:
        override_stmt = override_stmt.where(BudgetTarget.profile_id == profile_id)
    override_result = await db.execute(override_stmt)
    overrides: dict[uuid.UUID, float] = {
        t.category_id: float(t.amount) for t in override_result.scalars().all()
    }

    targets: dict[str, float | None] = {}
    for cat in categories:
        if cat.id in overrides:
            targets[str(cat.id)] = overrides[cat.id]
        elif cat.default_monthly_amount is not None:
            targets[str(cat.id)] = float(cat.default_monthly_amount)
        else:
            targets[str(cat.id)] = None

    return BudgetTargetMonthResponse(year=year, month=month, targets=targets)


# ── BudgetRollover ────────────────────────────────────────────────────────────

async def compute_and_store_rollover(
    db: AsyncSession,
    household_id: uuid.UUID,
    year: int,
    month: int,
    profile_id: uuid.UUID | None = None,
) -> RolloverComputeResponse:
    """
    Compute carry-forward amounts FROM the previous month and store them as
    rollover entries FOR (year, month).

      rollover_amount(M) = effective_target(M-1) - actual_spending(M-1)

    Positive = unspent balance (adds to next month's effective target).
    Negative = overspend (reduces next month's effective target).

    Only rollover-enabled categories are processed.  Recomputing is idempotent.
    Categories with no base target (neither override nor default) are skipped.
    """
    # Previous month
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    prev_first = date_type(prev_year, prev_month, 1)
    prev_last = date_type(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1])

    # Load rollover-enabled categories
    cat_stmt = select(BudgetCategory).where(
        BudgetCategory.household_id == household_id,
        BudgetCategory.archived_at.is_(None),
        BudgetCategory.rollover_enabled.is_(True),
    )
    if profile_id is not None:
        cat_stmt = cat_stmt.where(BudgetCategory.profile_id == profile_id)
    cat_result = await db.execute(cat_stmt)
    rollover_cats = cat_result.scalars().all()

    if not rollover_cats:
        return RolloverComputeResponse(
            year=year, month=month, categories_updated=0, total_carried_forward=0.0
        )

    cat_ids = [c.id for c in rollover_cats]

    # Load per-month overrides for prev_month (rollover cats only)
    override_stmt = select(BudgetTarget).where(
        BudgetTarget.household_id == household_id,
        BudgetTarget.year == prev_year,
        BudgetTarget.month == prev_month,
        BudgetTarget.category_id.in_(cat_ids),
    )
    override_result = await db.execute(override_stmt)
    prev_overrides: dict[uuid.UUID, float] = {
        t.category_id: float(t.amount) for t in override_result.scalars().all()
    }

    # Load rollover amount FROM the month before prev_month (so effective_target
    # for prev_month correctly includes its own carry-forward).
    prev_rollover_stmt = select(BudgetRolloverAmount).where(
        BudgetRolloverAmount.household_id == household_id,
        BudgetRolloverAmount.year == prev_year,
        BudgetRolloverAmount.month == prev_month,
        BudgetRolloverAmount.category_id.in_(cat_ids),
    )
    prev_rollover_result = await db.execute(prev_rollover_stmt)
    prev_rollover_map: dict[uuid.UUID, float] = {
        r.category_id: float(r.rollover_amount) for r in prev_rollover_result.scalars().all()
    }

    # Load actual spending per rollover category for prev_month.
    # Analytics use COALESCE(txn.profile_id, account.profile_id) for profile resolution.
    spend_stmt = (
        select(
            BudgetTransaction.category_id,
            func.sum(BudgetTransaction.amount).label("net"),
        )
        .join(BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id)
        .where(
            BudgetTransaction.household_id == household_id,
            BudgetTransaction.category_id.in_(cat_ids),
            BudgetTransaction.archived_at.is_(None),
            BudgetTransaction.is_transfer.is_(False),
            BudgetTransaction.date >= prev_first,
            BudgetTransaction.date <= prev_last,
        )
        .group_by(BudgetTransaction.category_id)
    )
    if profile_id is not None:
        spend_stmt = spend_stmt.where(
            func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id
        )
    spend_result = await db.execute(spend_stmt)
    spending_map: dict[uuid.UUID, float] = {
        row.category_id: float(abs(min(float(row.net or 0), 0)))
        for row in spend_result.all()
    }

    # Load existing rollover rows for (year, month) so we can upsert
    existing_stmt = select(BudgetRolloverAmount).where(
        BudgetRolloverAmount.household_id == household_id,
        BudgetRolloverAmount.year == year,
        BudgetRolloverAmount.month == month,
        BudgetRolloverAmount.category_id.in_(cat_ids),
    )
    existing_result = await db.execute(existing_stmt)
    existing_rows: dict[uuid.UUID, BudgetRolloverAmount] = {
        r.category_id: r for r in existing_result.scalars().all()
    }

    categories_updated = 0
    total_carried_forward = 0.0

    for cat in rollover_cats:
        # Base target for prev_month (override → default)
        if cat.id in prev_overrides:
            base_target = prev_overrides[cat.id]
        elif cat.default_monthly_amount is not None:
            base_target = float(cat.default_monthly_amount)
        else:
            continue  # no target set — nothing to carry forward

        prev_carry = prev_rollover_map.get(cat.id, 0.0)
        effective_prev = base_target + prev_carry
        actual_spending = spending_map.get(cat.id, 0.0)
        rollover_amount = effective_prev - actual_spending

        if cat.id in existing_rows:
            row = existing_rows[cat.id]
            row.rollover_amount = rollover_amount   # type: ignore[assignment]
            row.computed_at = datetime.now(timezone.utc)
        else:
            row = BudgetRolloverAmount(
                household_id=household_id,
                category_id=cat.id,
                year=year,
                month=month,
                rollover_amount=rollover_amount,
            )
            db.add(row)

        categories_updated += 1
        total_carried_forward += rollover_amount

    await db.commit()
    return RolloverComputeResponse(
        year=year,
        month=month,
        categories_updated=categories_updated,
        total_carried_forward=round(total_carried_forward, 2),
    )


# ── Analytics ─────────────────────────────────────────────────────────────────

async def get_analytics(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    year: int | None = None,
    month: int | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    account_id: uuid.UUID | None = None,
    profile_id: uuid.UUID | None = None,
) -> BudgetAnalyticsResponse:
    """
    Return per-category spending breakdown for a date range.

    Accepts either (year, month) for a calendar month, or (date_from, date_to)
    for an arbitrary range.  When date_from/date_to are supplied they take
    precedence; budget targets and rollover are omitted for non-month ranges
    since they are inherently monthly.

    Profile filtering: when profile_id is set, only transactions whose
    effective profile matches are included (COALESCE(txn.profile_id, account.profile_id)).
    """
    # Resolve date range
    is_month_range = date_from is None and date_to is None
    if is_month_range:
        resolved_year = year or date_type.today().year
        resolved_month = month or date_type.today().month
        first_day = date_type(resolved_year, resolved_month, 1)
        last_day = date_type(resolved_year, resolved_month, calendar.monthrange(resolved_year, resolved_month)[1])
    else:
        first_day = date_from or date_type.today().replace(day=1)
        last_day = date_to or date_type.today()
        resolved_year = first_day.year
        resolved_month = first_day.month

    stmt = (
        select(
            BudgetTransaction.category_id,
            BudgetCategory.name.label("category_name"),
            BudgetCategory.color.label("category_color"),
            BudgetCategory.icon.label("category_icon"),
            BudgetCategory.default_monthly_amount.label("default_monthly_amount"),
            BudgetCategoryGroup.name.label("group_name"),
            BudgetCategoryGroup.is_income.label("group_is_income"),
            func.sum(
                case((BudgetTransaction.amount < 0, BudgetTransaction.amount), else_=0)
            ).label("sum_expenses"),
            func.sum(
                case((BudgetTransaction.amount > 0, BudgetTransaction.amount), else_=0)
            ).label("sum_income"),
            func.count().label("transaction_count"),
        )
        .join(BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id)
        .outerjoin(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
        .outerjoin(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
        .where(
            BudgetTransaction.household_id == household_id,
            _transaction_visible_to(BudgetTransaction, user_id),
            BudgetTransaction.archived_at.is_(None),
            BudgetTransaction.is_transfer.is_(False),
            BudgetTransaction.date >= first_day,
            BudgetTransaction.date <= last_day,
        )
        .group_by(
            BudgetTransaction.category_id,
            BudgetCategory.name,
            BudgetCategory.color,
            BudgetCategory.icon,
            BudgetCategory.default_monthly_amount,
            BudgetCategoryGroup.name,
            BudgetCategoryGroup.is_income,
        )
    )
    if account_id is not None:
        stmt = stmt.where(BudgetTransaction.account_id == account_id)
    if profile_id is not None:
        # budget-011: resolve effective profile via COALESCE
        stmt = stmt.where(
            func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id
        )

    result = await db.execute(stmt)
    rows = result.all()

    # Budget targets, overrides, and rollover are month-scoped.
    # For arbitrary date ranges these are skipped (budgeted/remaining → null).
    overrides: dict[uuid.UUID, float] = {}
    rollover_map: dict[uuid.UUID, float] = {}
    total_targets = 0.0

    if is_month_range:
        # Load per-month target overrides for this month in one query.
        override_stmt = select(BudgetTarget).where(
            BudgetTarget.household_id == household_id,
            BudgetTarget.year == resolved_year,
            BudgetTarget.month == resolved_month,
        )
        if profile_id is not None:
            override_stmt = override_stmt.where(BudgetTarget.profile_id == profile_id)
        override_result = await db.execute(override_stmt)
        overrides = {
            t.category_id: float(t.amount) for t in override_result.scalars().all()
        }

        # Load stored rollover amounts for this month.
        rollover_stmt = select(BudgetRolloverAmount).where(
            BudgetRolloverAmount.household_id == household_id,
            BudgetRolloverAmount.year == resolved_year,
            BudgetRolloverAmount.month == resolved_month,
        )
        rollover_result = await db.execute(rollover_stmt)
        rollover_map = {
            r.category_id: float(r.rollover_amount) for r in rollover_result.scalars().all()
        }

        # Compute total_targets — sum of effective targets across ALL active categories.
        all_cats_stmt = select(
            BudgetCategory.id,
            BudgetCategory.default_monthly_amount,
        ).where(
            BudgetCategory.household_id == household_id,
            BudgetCategory.archived_at.is_(None),
        )
        if profile_id is not None:
            all_cats_stmt = all_cats_stmt.where(BudgetCategory.profile_id == profile_id)
        all_cats_result = await db.execute(all_cats_stmt)
        for cat_row in all_cats_result.all():
            cat_id = cat_row[0]
            if cat_id in overrides:
                base = overrides[cat_id]
            elif cat_row[1] is not None:
                base = float(cat_row[1])
            else:
                continue
            total_targets += base + rollover_map.get(cat_id, 0.0)

    by_category: list[BudgetCategoryAnalyticsEntry] = []
    total_expenses = 0.0
    total_income = 0.0
    total_count = 0
    total_budgeted = 0.0

    uncategorized_exp = 0.0
    uncategorized_inc = 0.0
    uncategorized_count = 0

    for row in rows:
        raw_exp = float(abs(row.sum_expenses or 0))
        inc = float(row.sum_income or 0)
        count = int(row.transaction_count or 0)
        # Use the explicit is_income flag on the group (set by the user in the
        # categories UI) rather than a hardcoded name match.  This lets users
        # name their income group anything they like (Salary, Inflows, etc.).
        is_income_group = bool(row.group_is_income)

        # For non-income categories, positive transactions are refunds/returns and
        # should net against expenses. Income-group categories are excluded from
        # expense tracking entirely.
        if is_income_group:
            exp = 0.0
            total_income += inc
        else:
            # Net refunds against spend; clamp at 0 (can't have negative category spend)
            exp = max(0.0, raw_exp - inc)

        total_expenses += exp
        total_count += count

        if row.category_name is None:
            uncategorized_exp += exp
            uncategorized_inc += inc
            uncategorized_count += count
        else:
            cat_id = row.category_id
            rollover_amt = rollover_map.get(cat_id, 0.0) if cat_id is not None else 0.0
            if cat_id is not None and cat_id in overrides:
                base_budgeted: float | None = overrides[cat_id]
            elif row.default_monthly_amount is not None:
                base_budgeted = float(row.default_monthly_amount)
            else:
                base_budgeted = None

            if base_budgeted is not None:
                budgeted: float | None = base_budgeted + rollover_amt
                total_budgeted += budgeted
                remaining: float | None = budgeted - exp
                is_over = exp > budgeted
            else:
                budgeted = None
                remaining = None
                is_over = False

            by_category.append(BudgetCategoryAnalyticsEntry(
                category_id=row.category_id,
                category_name=row.category_name,
                category_color=row.category_color,
                category_icon=row.category_icon,
                total_expenses=exp,
                total_income=inc,
                transaction_count=count,
                budgeted=budgeted,
                remaining=remaining,
                is_over_budget=is_over,
                rollover_amount=rollover_amt,
            ))

    if uncategorized_count > 0:
        by_category.append(BudgetCategoryAnalyticsEntry(
            category_id=None,
            category_name="Uncategorized",
            category_color=None,
            category_icon=None,
            total_expenses=uncategorized_exp,
            total_income=uncategorized_inc,
            transaction_count=uncategorized_count,
            budgeted=None,
            remaining=None,
            is_over_budget=False,
            rollover_amount=0.0,
        ))

    by_category.sort(key=lambda e: e.total_expenses, reverse=True)

    return BudgetAnalyticsResponse(
        year=resolved_year,
        month=resolved_month,
        date_from=first_day,
        date_to=last_day,
        total_expenses=total_expenses,
        total_income=total_income,
        transaction_count=total_count,
        total_budgeted=total_budgeted,
        total_targets=total_targets,
        by_category=by_category,
    )


async def get_profit_analytics(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    year: int,
    month: int,
    profile_id: uuid.UUID,
) -> BudgetProfitAnalyticsResponse:
    """
    P&L analytics view for profit_tracking profiles (budget-012).

    Returns revenue vs expenses, net profit, and MRR metrics (budget-013).
    """
    first_day = date_type(year, month, 1)
    last_day = date_type(year, month, calendar.monthrange(year, month)[1])

    # Reuse the same per-category aggregation
    base = await get_analytics(
        db, household_id, user_id,
        year=year, month=month, profile_id=profile_id,
    )

    # MRR calculation (budget-013): sum income from is_recurring_revenue categories
    mrr_cats_stmt = select(BudgetCategory.id).where(
        BudgetCategory.household_id == household_id,
        BudgetCategory.profile_id == profile_id,
        BudgetCategory.is_recurring_revenue.is_(True),
        BudgetCategory.archived_at.is_(None),
    )
    mrr_cats_result = await db.execute(mrr_cats_stmt)
    mrr_cat_ids = {r for r in mrr_cats_result.scalars().all()}

    mrr_actual = 0.0
    if mrr_cat_ids:
        mrr_stmt = select(func.sum(BudgetTransaction.amount)).join(
            BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id
        ).where(
            BudgetTransaction.household_id == household_id,
            BudgetTransaction.category_id.in_(mrr_cat_ids),
            BudgetTransaction.amount > 0,
            BudgetTransaction.archived_at.is_(None),
            BudgetTransaction.is_transfer.is_(False),
            BudgetTransaction.date >= first_day,
            BudgetTransaction.date <= last_day,
            func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id,
        )
        mrr_result = await db.execute(mrr_stmt)
        mrr_actual = float(mrr_result.scalar_one() or 0)

    # Previous month MRR for growth calculation
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    prev_first = date_type(prev_year, prev_month, 1)
    prev_last = date_type(prev_year, prev_month, calendar.monthrange(prev_year, prev_month)[1])

    mrr_prev = 0.0
    if mrr_cat_ids:
        prev_mrr_stmt = select(func.sum(BudgetTransaction.amount)).join(
            BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id
        ).where(
            BudgetTransaction.household_id == household_id,
            BudgetTransaction.category_id.in_(mrr_cat_ids),
            BudgetTransaction.amount > 0,
            BudgetTransaction.archived_at.is_(None),
            BudgetTransaction.is_transfer.is_(False),
            BudgetTransaction.date >= prev_first,
            BudgetTransaction.date <= prev_last,
            func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id,
        )
        prev_mrr_result = await db.execute(prev_mrr_stmt)
        mrr_prev = float(prev_mrr_result.scalar_one() or 0)

    mrr_growth_pct: float | None = None
    if mrr_prev > 0:
        mrr_growth_pct = round((mrr_actual - mrr_prev) / mrr_prev * 100, 2)

    return BudgetProfitAnalyticsResponse(
        year=year,
        month=month,
        date_from=first_day,
        date_to=last_day,
        total_revenue=base.total_income,
        total_expenses=base.total_expenses,
        net_profit=round(base.total_income - base.total_expenses, 2),
        transaction_count=base.transaction_count,
        by_category=base.by_category,
        mrr_actual=round(mrr_actual, 2),
        arr_projected=round(mrr_actual * 12, 2),
        mrr_prev_month=round(mrr_prev, 2),
        mrr_growth_pct=mrr_growth_pct,
    )


# ── BudgetTransaction ─────────────────────────────────────────────────────────

async def list_transactions(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    uncategorized: bool = False,
    txn_type: str | None = None,
    scope: str | None = None,
    date_from: Any | None = None,
    date_to: Any | None = None,
    include_archived: bool = False,
    limit: int = 20,
    offset: int = 0,
    profile_id: uuid.UUID | None = None,
    search: str | None = None,
) -> BudgetTransactionListResponse:
    base = (
        select(BudgetTransaction)
        .join(BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id)
        .where(
            BudgetTransaction.household_id == household_id,
            _transaction_visible_to(BudgetTransaction, user_id),
        )
    )
    if not include_archived:
        base = base.where(BudgetTransaction.archived_at.is_(None))
    if account_id is not None:
        base = base.where(BudgetTransaction.account_id == account_id)
    if category_id is not None:
        base = base.where(BudgetTransaction.category_id == category_id)
    # txn_type supersedes the legacy uncategorized bool
    effective_type = txn_type or ("uncategorized" if uncategorized else None)
    if effective_type == "uncategorized":
        base = base.where(
            BudgetTransaction.category_id.is_(None),
            BudgetTransaction.is_transfer.is_(False),
        )
    elif effective_type == "transfers":
        base = base.where(BudgetTransaction.is_transfer.is_(True))
    elif effective_type == "income":
        base = base.where(
            BudgetTransaction.amount > 0,
            BudgetTransaction.is_transfer.is_(False),
        )
    elif effective_type == "expenses":
        base = base.where(
            BudgetTransaction.amount < 0,
            BudgetTransaction.is_transfer.is_(False),
        )
    elif effective_type == "recurring":
        base = base.where(BudgetTransaction.recurring.is_not(None))
    if scope is not None:
        base = base.where(BudgetTransaction.scope == scope)
    if date_from is not None:
        base = base.where(BudgetTransaction.date >= date_from)
    if date_to is not None:
        base = base.where(BudgetTransaction.date <= date_to)
    if profile_id is not None:
        base = base.where(
            func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id
        )
    if search:
        q = f"%{search.lower()}%"
        base = base.where(
            func.lower(BudgetTransaction.description).like(q)
            | func.lower(func.coalesce(BudgetTransaction.merchant_name, "")).like(q)
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    stmt = base.order_by(BudgetTransaction.date.desc(), BudgetTransaction.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    items = [BudgetTransactionResponse.model_validate(t) for t in result.scalars().all()]

    return BudgetTransactionListResponse(items=items, total=total, limit=limit, offset=offset)


async def get_summary(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    date_from: Any | None = None,
    date_to: Any | None = None,
    profile_id: uuid.UUID | None = None,
) -> BudgetSummaryResponse:
    """
    Return aggregate income / expense totals for the given date range.
    Does a single SQL aggregation — does not load transaction rows.
    """
    stmt = select(
        func.count().label("transaction_count"),
        func.sum(
            # Count positive transactions as income only when their category's
            # group has is_income=True.  Uses the explicit flag instead of a
            # name match so users can call their income group anything they like.
            case(
                (
                    and_(
                        BudgetTransaction.amount > 0,
                        BudgetCategoryGroup.is_income == True,  # noqa: E712
                    ),
                    BudgetTransaction.amount,
                ),
                else_=0,
            )
        ).label("total_income"),
        func.sum(
            case((BudgetTransaction.amount < 0, BudgetTransaction.amount), else_=0)
        ).label("total_expenses"),
    ).join(
        BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id
    ).outerjoin(
        BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id
    ).outerjoin(
        BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id
    ).where(
        BudgetTransaction.household_id == household_id,
        _transaction_visible_to(BudgetTransaction, user_id),
        BudgetTransaction.archived_at.is_(None),
        BudgetTransaction.is_transfer.is_(False),
    )
    if account_id is not None:
        stmt = stmt.where(BudgetTransaction.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(BudgetTransaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(BudgetTransaction.date <= date_to)
    if profile_id is not None:
        stmt = stmt.where(
            func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id
        )

    result = await db.execute(stmt)
    row = result.one()
    return BudgetSummaryResponse(
        total_income=float(row.total_income or 0),
        total_expenses=float(abs(row.total_expenses or 0)),
        transaction_count=int(row.transaction_count or 0),
        date_from=date_from,
        date_to=date_to,
    )


async def get_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> BudgetTransaction | None:
    stmt = select(BudgetTransaction).where(
        BudgetTransaction.id == transaction_id,
        BudgetTransaction.household_id == household_id,
        _transaction_visible_to(BudgetTransaction, user_id),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _maybe_check_thresholds(
    db: AsyncSession,
    household_id: uuid.UUID,
    txn_date: date_type | None,
) -> None:
    """
    Run check_budget_thresholds only when the transaction falls in the current
    calendar month — no point checking historical imports.  Errors are swallowed
    so a threshold failure never blocks the primary write.
    """
    today = date_type.today()
    if txn_date is None or txn_date.year != today.year or txn_date.month != today.month:
        return
    try:
        await check_budget_thresholds(db, household_id)
        await db.commit()
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Budget threshold check failed for household %s: %s", household_id, exc
        )


async def create_transaction(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: BudgetTransactionCreate,
) -> BudgetTransactionResponse:
    """
    Create a single transaction. The account must belong to this household.
    If scope is not provided it is inherited from the account's scope
    (personal account → private, shared account → shared).
    """
    # Resolve account for scope inheritance and owner_user_id
    account = await get_account(db, data.account_id, household_id)
    if account is None:
        raise ValueError(f"Account {data.account_id} not found in household")

    # Scope inheritance: personal account → private, shared account → shared
    scope = data.scope
    if scope is None:
        scope = "private" if account.scope == "personal" else "shared"

    dedup_hash = _compute_dedup_hash(data.account_id, data.date, data.amount, data.description)

    txn = BudgetTransaction(
        household_id=household_id,
        account_id=data.account_id,
        owner_user_id=account.owner_user_id,
        category_id=data.category_id,
        date=data.date,
        amount=data.amount,
        currency=data.currency,
        description=data.description,
        merchant_name=data.merchant_name,
        notes=data.notes,
        scope=scope,
        split_override=data.split_override,
        import_source=data.import_source,
        external_id=data.external_id,
        dedup_hash=dedup_hash,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    await _maybe_check_thresholds(db, household_id, txn.date)
    return BudgetTransactionResponse.model_validate(txn)


async def update_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: BudgetTransactionUpdate,
) -> BudgetTransactionResponse | None:
    txn = await get_transaction(db, transaction_id, household_id, user_id)
    if txn is None:
        return None
    for field in data.model_fields_set:
        value = getattr(data, field)
        # JSONB fields require plain dicts — serialize Pydantic sub-models
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        setattr(txn, field, value)
    txn.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(txn)
    # Re-check thresholds when the category or date was touched
    if "category_id" in data.model_fields_set or "date" in data.model_fields_set:
        await _maybe_check_thresholds(db, household_id, txn.date)
    return BudgetTransactionResponse.model_validate(txn)


async def reattribute_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    target_profile_id: uuid.UUID | None,
) -> ReattributeResponse:
    """
    budget-011: Re-attribute a transaction to a different profile for analytics.

    Sets txn.profile_id to the target. When target_profile_id is None, reverts
    to the account's profile (clears the override).

    Returns whether the target category has a split_config (so the UI can prompt
    to apply splitting if needed).
    """
    txn = await get_transaction(db, transaction_id, household_id, user_id)
    if txn is None:
        raise ValueError("Transaction not found")

    if target_profile_id is not None:
        # Verify the target profile belongs to this household
        p = await get_profile(db, target_profile_id, household_id)
        if p is None:
            raise ValueError("Target profile not found")

    txn.profile_id = target_profile_id
    txn.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Check if the target category has split_config
    split_prompt = False
    if txn.category_id is not None and target_profile_id is not None:
        cat = await get_category(db, txn.category_id, household_id)
        split_prompt = cat is not None and cat.split_config is not None

    return ReattributeResponse(
        transaction_id=transaction_id,
        target_profile_id=target_profile_id,
        split_prompt=split_prompt,
    )


# ── Transaction description tokeniser ─────────────────────────────────────────

_NOISE_RE = re.compile(
    r"""
    \b\d{2}/\d{2}(?:/\d{2,4})?\b  # dates: 05/18, 05/18/24
    | \b\d{4,}\b                   # long numbers: 9215, 14159490635
    | \+\d+                        # phone with + prefix
    | \#\d+                        # store numbers: #91
    """,
    re.VERBOSE,
)

_NOISE_WORDS = frozenset({
    "POS", "ACH", "SP", "SQ", "TST", "CHECKCARD", "PURCHASE", "DEBIT",
    "CREDIT", "AUTOPAY", "PAYMENT", "TRANSFER", "WITHDRAWAL", "DEPOSIT",
    "ONLINE", "RECURRING", "PREAUTH", "AUTH", "PMT", "DDA", "EFT",
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
    "AB", "BC", "MB", "NB", "NL", "NS", "ON", "PE", "QC", "SK",
})


def _significant_tokens(text: str) -> frozenset[str]:
    upper = text.upper()
    cleaned = _NOISE_RE.sub(" ", upper)
    cleaned = cleaned.replace("*", " ")
    tokens = re.split(r"[\s.,+\-/\\|:;]+", cleaned)
    return frozenset(
        t for t in tokens
        if len(t) >= 3
        and t not in _NOISE_WORDS
        and not t.isdigit()
    )


async def apply_category_to_similar(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    category_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[int, bool]:
    """
    Apply category_id to all transactions (categorized or not) that appear to
    be from the same merchant as the source transaction.
    """
    source = await get_transaction(db, transaction_id, household_id, user_id)
    if source is None:
        return 0, False

    source_text = source.merchant_name or source.description or ""
    source_tokens = _significant_tokens(source_text)
    if not source_tokens:
        return 0, False

    stmt = select(BudgetTransaction).where(
        BudgetTransaction.household_id == household_id,
        BudgetTransaction.archived_at.is_(None),
        BudgetTransaction.id != transaction_id,
    )
    result = await db.execute(stmt)
    candidates = result.scalars().all()

    def _hit_count(token: str) -> int:
        t = token.lower()
        return sum(
            1 for c in candidates
            if t in (c.description or "").lower()
            or t in (c.merchant_name or "").lower()
        )

    best_token = min(source_tokens, key=_hit_count)
    search = best_token.lower()

    similar = [
        c for c in candidates
        if search in (c.description or "").lower()
        or search in (c.merchant_name or "").lower()
    ]

    updated = 0
    for txn in similar:
        txn.category_id = category_id
        txn.updated_at = datetime.now(timezone.utc)
        updated += 1

    keyword_added = False
    cat_stmt = select(BudgetCategory).where(
        BudgetCategory.id == category_id,
        BudgetCategory.household_id == household_id,
    )
    cat_result = await db.execute(cat_stmt)
    category_obj = cat_result.scalar_one_or_none()
    if category_obj is not None:
        existing_lower = {k.lower() for k in (category_obj.keywords or [])}
        if search not in existing_lower:
            category_obj.keywords = list(category_obj.keywords or []) + [best_token.title()]
            category_obj.updated_at = datetime.now(timezone.utc)
            keyword_added = True

    if updated > 0 or keyword_added:
        await db.commit()
        await _maybe_check_thresholds(db, household_id, date_type.today())

    return updated, keyword_added


async def apply_transfer_to_similar(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    """
    Mark all non-transfer transactions that appear to be from the same merchant
    as the source transaction as is_transfer=True.  Also clears their category
    since transfers are excluded from spending analytics.
    """
    source = await get_transaction(db, transaction_id, household_id, user_id)
    if source is None:
        return 0

    source_text = source.merchant_name or source.description or ""
    source_tokens = _significant_tokens(source_text)
    if not source_tokens:
        return 0

    stmt = select(BudgetTransaction).where(
        BudgetTransaction.household_id == household_id,
        BudgetTransaction.is_transfer == False,  # noqa: E712
        BudgetTransaction.archived_at.is_(None),
        BudgetTransaction.id != transaction_id,
    )
    result = await db.execute(stmt)
    candidates = result.scalars().all()

    def _hit_count(token: str) -> int:
        t = token.lower()
        return sum(
            1 for c in candidates
            if t in (c.description or "").lower()
            or t in (c.merchant_name or "").lower()
        )

    best_token = min(source_tokens, key=_hit_count)
    search = best_token.lower()

    similar = [
        c for c in candidates
        if search in (c.description or "").lower()
        or search in (c.merchant_name or "").lower()
    ]

    updated = 0
    for txn in similar:
        txn.is_transfer = True
        txn.category_id = None  # clear category — transfers don't belong to a spending bucket
        txn.updated_at = datetime.now(timezone.utc)
        updated += 1

    if updated > 0:
        await db.commit()

    return updated


async def auto_categorize_transactions(
    db: AsyncSession,
    household_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
) -> int:
    """
    Assign categories to uncategorized transactions using keyword matching.
    """
    cat_stmt = select(BudgetCategory).where(
        BudgetCategory.household_id == household_id,
        BudgetCategory.archived_at.is_(None),
        BudgetCategory.keywords.isnot(None),
    )
    cat_result = await db.execute(cat_stmt)
    categories = cat_result.scalars().all()

    if not categories:
        return 0

    txn_stmt = select(BudgetTransaction).where(
        BudgetTransaction.household_id == household_id,
        BudgetTransaction.category_id.is_(None),
        BudgetTransaction.archived_at.is_(None),
        BudgetTransaction.is_transfer.is_(False),
    )
    if account_id is not None:
        txn_stmt = txn_stmt.where(BudgetTransaction.account_id == account_id)
    txn_result = await db.execute(txn_stmt)
    transactions = txn_result.scalars().all()

    updated = 0
    for txn in transactions:
        haystack = " ".join(
            filter(None, [txn.description, txn.merchant_name])
        ).lower()
        for cat in categories:
            keywords: list[str] = cat.keywords or []
            if any(kw.strip().lower() in haystack for kw in keywords if kw.strip()):
                txn.category_id = cat.id
                updated += 1
                break

    if updated:
        await db.commit()
    return updated


async def delete_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    txn = await get_transaction(db, transaction_id, household_id, user_id)
    if txn is None:
        return False
    await db.delete(txn)
    await db.commit()
    return True


async def delete_all_transactions(
    db: AsyncSession,
    household_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
) -> int:
    stmt = delete(BudgetTransaction).where(
        BudgetTransaction.household_id == household_id
    )
    if account_id is not None:
        stmt = stmt.where(BudgetTransaction.account_id == account_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount  # type: ignore[return-value]


async def export_transactions_csv(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    scope: str | None = None,
    date_from: Any | None = None,
    date_to: Any | None = None,
    profile_id: uuid.UUID | None = None,
) -> str:
    """
    Return all matching transactions as a UTF-8 CSV string.
    Columns: date, merchant, amount, category, notes.
    """
    stmt = (
        select(BudgetTransaction, BudgetCategory.name.label("category_name"))
        .join(BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id)
        .outerjoin(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
        .where(
            BudgetTransaction.household_id == household_id,
            _transaction_visible_to(BudgetTransaction, user_id),
            BudgetTransaction.archived_at.is_(None),
        )
    )
    if account_id is not None:
        stmt = stmt.where(BudgetTransaction.account_id == account_id)
    if category_id is not None:
        stmt = stmt.where(BudgetTransaction.category_id == category_id)
    if scope is not None:
        stmt = stmt.where(BudgetTransaction.scope == scope)
    if date_from is not None:
        stmt = stmt.where(BudgetTransaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(BudgetTransaction.date <= date_to)
    if profile_id is not None:
        stmt = stmt.where(
            func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id
        )
    stmt = stmt.order_by(BudgetTransaction.date.desc(), BudgetTransaction.created_at.desc())

    result = await db.execute(stmt)
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "merchant", "amount", "category", "notes"])
    for txn, category_name in rows:
        writer.writerow([
            str(txn.date),
            txn.merchant_name or txn.description,
            f"{float(txn.amount):.2f}",
            category_name or "",
            txn.notes or "",
        ])
    return output.getvalue()


async def bulk_import_transactions(
    db: AsyncSession,
    household_id: uuid.UUID,
    account_id: uuid.UUID,
    import_source: str,
    transactions: list[BudgetTransactionCreate],
) -> BudgetTransactionBulkImportResponse:
    """
    Insert a batch of transactions, skipping any that are duplicates.
    """
    account = await get_account(db, account_id, household_id)
    if account is None:
        raise ValueError(f"Account {account_id} not found in household")

    existing_stmt = select(
        BudgetTransaction.external_id,
        BudgetTransaction.dedup_hash,
    ).where(
        BudgetTransaction.account_id == account_id,
        BudgetTransaction.household_id == household_id,
    )
    existing_result = await db.execute(existing_stmt)
    existing_rows = existing_result.all()
    existing_external_ids = {r.external_id for r in existing_rows if r.external_id}
    existing_dedup_hashes = {r.dedup_hash for r in existing_rows if r.dedup_hash}

    inserted = 0
    skipped = 0

    for t in transactions:
        dedup_hash = _compute_dedup_hash(account_id, t.date, t.amount, t.description)

        if t.external_id and t.external_id in existing_external_ids:
            skipped += 1
            continue
        if dedup_hash in existing_dedup_hashes:
            skipped += 1
            continue

        scope = t.scope
        if scope is None:
            scope = "private" if account.scope == "personal" else "shared"

        txn = BudgetTransaction(
            household_id=household_id,
            account_id=account_id,
            owner_user_id=account.owner_user_id,
            category_id=t.category_id,
            date=t.date,
            amount=t.amount,
            currency=t.currency,
            description=t.description,
            merchant_name=t.merchant_name,
            notes=t.notes,
            scope=scope,
            split_override=t.split_override,
            import_source=import_source,
            external_id=t.external_id,
            dedup_hash=dedup_hash,
            running_balance=t.running_balance,
        )
        db.add(txn)

        if t.external_id:
            existing_external_ids.add(t.external_id)
        existing_dedup_hashes.add(dedup_hash)
        inserted += 1

    await db.commit()

    # Check thresholds if any inserted transactions fall in the current month
    if inserted > 0:
        today = date_type.today()
        current_month_dates = [
            t.date for t in transactions
            if t.date is not None and t.date.year == today.year and t.date.month == today.month
        ]
        if current_month_dates:
            await _maybe_check_thresholds(db, household_id, current_month_dates[0])

    return BudgetTransactionBulkImportResponse(inserted=inserted, skipped=skipped)


# ── budget-004: Recurring transactions ───────────────────────────────────────

def _recurring_dates_for_month(
    template_date: date_type,
    rule: dict,
    year: int,
    month: int,
) -> list[date_type]:
    """
    Return all dates within (year, month) on which a recurring transaction
    should appear, given the template date and rule.

    frequency="monthly": one date per month, same day-of-month (clamped to
    the last day of the target month). Respects interval (e.g. interval=2
    means every other month starting from the template month).

    frequency="weekly": every N weeks from the template date, any occurrence
    that falls inside the target month.

    frequency="bi_weekly": every 2 weeks (alias for weekly + interval=2).

    frequency="semi_monthly": twice a month — on the 15th and the 30th
    (clamped to the last day of the month for short months). If either date
    falls on a Saturday or Sunday it is moved to the preceding Friday, matching
    typical payroll "pay early if the date lands on a weekend" behaviour.
    """
    import calendar as _cal

    def _prev_friday_if_weekend(d: date_type) -> date_type:
        """Return d unchanged, or the preceding Friday if d is Sat/Sun."""
        wd = d.weekday()  # 0=Mon … 5=Sat, 6=Sun
        if wd == 5:
            return date_type.fromordinal(d.toordinal() - 1)
        if wd == 6:
            return date_type.fromordinal(d.toordinal() - 2)
        return d

    frequency = rule.get("frequency", "monthly")
    interval = max(1, int(rule.get("interval", 1)))
    end_date_str = rule.get("end_date")
    end_date = date_type.fromisoformat(end_date_str) if end_date_str else None

    last_day = _cal.monthrange(year, month)[1]
    month_start = date_type(year, month, 1)
    month_end = date_type(year, month, last_day)

    results: list[date_type] = []

    if frequency == "monthly":
        # Only generate if this month aligns with the interval
        months_since = (year - template_date.year) * 12 + (month - template_date.month)
        if months_since < 0 or months_since % interval != 0:
            return []
        day = min(template_date.day, last_day)
        target = date_type(year, month, day)
        if target <= template_date:
            return []  # don't generate for the template's own month or earlier
        if end_date and target > end_date:
            return []
        results.append(target)

    elif frequency in ("weekly", "bi_weekly"):
        # bi_weekly is weekly with interval=2; if the rule itself says bi_weekly
        # normalise the interval so the walk step is correct.
        effective_interval = 2 if frequency == "bi_weekly" else interval
        cursor = template_date
        while cursor <= month_end:
            cursor_next = date_type.fromordinal(cursor.toordinal() + effective_interval * 7)
            if month_start <= cursor_next <= month_end:
                if cursor_next > template_date:  # never duplicate the original
                    if not (end_date and cursor_next > end_date):
                        results.append(cursor_next)
            cursor = cursor_next

    elif frequency == "semi_monthly":
        # Fire on the 15th and the 30th every month (regardless of template
        # day-of-month).  The 30th is clamped to the last day of the month for
        # months shorter than 30 days.  Both dates are adjusted to the preceding
        # Friday when they land on a weekend.
        months_since = (year - template_date.year) * 12 + (month - template_date.month)
        if months_since < 0:
            return []
        day1 = _prev_friday_if_weekend(date_type(year, month, 15))
        day2 = _prev_friday_if_weekend(date_type(year, month, min(30, last_day)))
        for d in sorted({day1, day2}):
            if d > template_date and month_start <= d <= month_end:
                if not (end_date and d > end_date):
                    results.append(d)

    return results


async def ensure_recurring_for_month(
    db: AsyncSession,
    household_id: uuid.UUID,
    year: int,
    month: int,
) -> RecurringGenerateResponse:
    """
    budget-004: Idempotently generate recurring transaction instances for the
    given month from all active templates in the household.

    A "template" is any non-archived transaction with recurring IS NOT NULL.
    Generated instances have recurring=NULL and recurring_template_id set.

    Safe to call multiple times — existing instances are detected by
    (recurring_template_id, date) and skipped.
    """
    import calendar as _cal

    last_day = _cal.monthrange(year, month)[1]
    month_start = date_type(year, month, 1)
    month_end = date_type(year, month, last_day)

    # 1. Load all recurring templates for this household
    tmpl_stmt = (
        select(BudgetTransaction)
        .where(
            BudgetTransaction.household_id == household_id,
            BudgetTransaction.recurring.is_not(None),
            BudgetTransaction.archived_at.is_(None),
        )
    )
    tmpl_result = await db.execute(tmpl_stmt)
    templates = tmpl_result.scalars().all()

    if not templates:
        return RecurringGenerateResponse(year=year, month=month, generated=0)

    template_ids = [t.id for t in templates]

    # 2. Load existing instances for this month (to avoid duplicates)
    existing_stmt = select(
        BudgetTransaction.recurring_template_id,
        BudgetTransaction.date,
    ).where(
        BudgetTransaction.household_id == household_id,
        BudgetTransaction.recurring_template_id.in_(template_ids),
        BudgetTransaction.date >= month_start,
        BudgetTransaction.date <= month_end,
        BudgetTransaction.archived_at.is_(None),
    )
    existing_result = await db.execute(existing_stmt)
    existing: set[tuple] = {(row.recurring_template_id, row.date) for row in existing_result}

    generated = 0
    for tmpl in templates:
        rule = tmpl.recurring or {}
        target_dates = _recurring_dates_for_month(tmpl.date, rule, year, month)
        for target_date in target_dates:
            if (tmpl.id, target_date) in existing:
                continue  # already generated

            dedup_hash = _compute_dedup_hash(tmpl.account_id, target_date, float(tmpl.amount), tmpl.description)
            instance = BudgetTransaction(
                household_id=tmpl.household_id,
                account_id=tmpl.account_id,
                owner_user_id=tmpl.owner_user_id,
                category_id=tmpl.category_id,
                profile_id=tmpl.profile_id,
                date=target_date,
                amount=float(tmpl.amount),
                currency=tmpl.currency,
                description=tmpl.description,
                merchant_name=tmpl.merchant_name,
                notes=tmpl.notes,
                scope=tmpl.scope,
                split_override=tmpl.split_override,
                import_source=None,   # recurring instances are identified by recurring_template_id
                recurring=None,
                recurring_template_id=tmpl.id,
                dedup_hash=dedup_hash,
            )
            db.add(instance)
            generated += 1

    if generated:
        await db.commit()

    return RecurringGenerateResponse(year=year, month=month, generated=generated)


# ── budget-020: Income forecasting ────────────────────────────────────────────

async def get_income_forecast(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    year: int,
    month: int,
    profile_id: uuid.UUID | None = None,
) -> IncomeForecastResponse:
    """
    Project recurring income for (year, month) without creating any DB rows.

    Uses _recurring_dates_for_month to determine which recurring templates
    (amount > 0, non-transfer) fire in the target month. Returns per-source
    breakdown plus the month's total_targets so the UI can show
    left_to_allocate = projected_income - total_targets.

    For current/past months also returns actual_income from get_analytics.
    """
    today = date_type.today()
    is_future = (year, month) > (today.year, today.month)

    # Load recurring income templates (amount > 0, non-transfer, not archived).
    # Always join BudgetAccount so the profile COALESCE filter is available
    # regardless of whether profile_id is supplied — avoids the SQLAlchemy
    # join-order issue that occurs when BudgetAccount is added conditionally
    # after BudgetCategory has already been outer-joined.
    tmpl_stmt = (
        select(
            BudgetTransaction,
            BudgetCategory.name.label("category_name"),
        )
        .join(BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id)
        .outerjoin(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
        .where(
            BudgetTransaction.household_id == household_id,
            BudgetTransaction.recurring.is_not(None),
            BudgetTransaction.amount > 0,
            BudgetTransaction.is_transfer.is_(False),
            BudgetTransaction.archived_at.is_(None),
        )
    )
    if profile_id is not None:
        tmpl_stmt = tmpl_stmt.where(
            func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id
        )
    tmpl_result = await db.execute(tmpl_stmt)
    tmpl_rows = tmpl_result.all()

    # Project occurrences for the target month
    sources: list[IncomeForecastSource] = []
    projected_income = 0.0

    for row in tmpl_rows:
        tmpl = row[0]
        cat_name = row[1]
        rule = tmpl.recurring or {}
        target_dates = _recurring_dates_for_month(tmpl.date, rule, year, month)

        # _recurring_dates_for_month intentionally skips the template's own month
        # (to avoid duplicating the original transaction when generating instances).
        # For forecasting we DO want to show that month's occurrence, so add it back.
        if tmpl.date.year == year and tmpl.date.month == month and tmpl.date not in target_dates:
            target_dates = [tmpl.date] + list(target_dates)

        for target_date in target_dates:
            amt = float(tmpl.amount)
            projected_income += amt
            sources.append(IncomeForecastSource(
                template_id=tmpl.id,
                description=tmpl.description,
                amount=amt,
                category_id=tmpl.category_id,
                category_name=cat_name,
                expected_date=target_date,
            ))

    sources.sort(key=lambda s: s.expected_date)

    # Actual income for current/past months (reuse analytics)
    actual_income = 0.0
    total_targets = 0.0
    if not is_future:
        analytics = await get_analytics(
            db, household_id, user_id,
            year=year, month=month, profile_id=profile_id,
        )
        actual_income = analytics.total_income
        total_targets = analytics.total_targets
    else:
        # For future months, still compute targets
        analytics = await get_analytics(
            db, household_id, user_id,
            year=year, month=month, profile_id=profile_id,
        )
        total_targets = analytics.total_targets

    left_to_allocate = round(projected_income - total_targets, 2)

    return IncomeForecastResponse(
        year=year,
        month=month,
        projected_income=round(projected_income, 2),
        actual_income=round(actual_income, 2),
        sources=sources,
        total_targets=round(total_targets, 2),
        left_to_allocate=left_to_allocate,
        is_future_month=is_future,
    )


# ── Spending trends ────────────────────────────────────────────────────────────

async def get_spending_trends(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    months: int = 6,
    profile_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
) -> list[dict]:
    """
    Return monthly income / expense totals for the last `months` calendar months
    (including the current month), ordered oldest→newest.
    Also fetches budget targets for each month to populate total_budgeted.
    """
    today = date_type.today()

    # Build list of (year, month) pairs, oldest first
    pairs: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(months):
        pairs.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    pairs.reverse()

    results = []
    for year, month in pairs:
        first_day = date_type(year, month, 1)
        last_day = date_type(year, month, calendar.monthrange(year, month)[1])

        # Aggregate income + expenses for this month.
        # Income is scoped to categories in a group named "Income" (matches get_analytics/get_summary).
        agg_stmt = (
            select(
                func.sum(
                    case(
                        (
                            and_(
                                BudgetTransaction.amount > 0,
                                func.lower(BudgetCategoryGroup.name) == "income",
                            ),
                            BudgetTransaction.amount,
                        ),
                        else_=0,
                    )
                ).label("total_income"),
                func.sum(
                    case(
                        (BudgetTransaction.amount < 0, BudgetTransaction.amount),
                        (
                            and_(
                                BudgetTransaction.amount > 0,
                                func.lower(func.coalesce(BudgetCategoryGroup.name, "")) != "income",
                            ),
                            BudgetTransaction.amount,
                        ),
                        else_=0,
                    )
                ).label("total_expenses"),
            )
            .join(BudgetAccount, BudgetTransaction.account_id == BudgetAccount.id)
            .outerjoin(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .outerjoin(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                BudgetTransaction.household_id == household_id,
                BudgetTransaction.archived_at.is_(None),
                BudgetTransaction.is_transfer.is_(False),
                BudgetTransaction.date >= first_day,
                BudgetTransaction.date <= last_day,
                _transaction_visible_to(BudgetTransaction, user_id),
            )
        )
        if account_id is not None:
            agg_stmt = agg_stmt.where(BudgetTransaction.account_id == account_id)
        if profile_id is not None:
            agg_stmt = agg_stmt.where(
                func.coalesce(BudgetTransaction.profile_id, BudgetAccount.profile_id) == profile_id
            )

        agg_row = (await db.execute(agg_stmt)).one()
        total_income = float(agg_row.total_income or 0)
        total_expenses = abs(float(agg_row.total_expenses or 0))

        # Sum effective budget targets for this month
        targets_q = select(BudgetTarget).where(
            BudgetTarget.household_id == household_id,
            BudgetTarget.year == year,
            BudgetTarget.month == month,
        )
        if profile_id is not None:
            targets_q = targets_q.where(BudgetTarget.profile_id == profile_id)
        target_rows = list((await db.execute(targets_q)).scalars().all())
        total_budgeted = sum(float(t.amount) for t in target_rows)

        results.append({
            "year": year,
            "month": month,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "total_budgeted": total_budgeted,
            "net": total_income - total_expenses,
        })

    return results


# ── Teller bank sync ──────────────────────────────────────────────────────────

def get_teller_config() -> TellerConfigResponse:
    """Return public Teller configuration for the frontend widget."""
    enabled = teller_client.is_configured()
    return TellerConfigResponse(
        enabled=enabled,
        app_id=settings.teller_app_id or None,
        environment=settings.teller_environment,
    )


async def connect_teller_enrollment(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: TellerConnectRequest,
) -> list[BudgetAccountResponse]:
    """
    Process a successful Teller Connect callback.

    Calls Teller GET /accounts with the new access token to discover all
    bank accounts in the enrollment.  For each account:
      - If a BudgetAccount already exists with the same teller_account_id,
        refresh its enrollment/token/cursor (re-authentication flow).
      - Otherwise create a new BudgetAccount owned by the current user.

    The account is placed in the user's default Personal profile unless no
    profiles exist, in which case profile_id is left NULL.

    account_ids filter: when data.account_ids is non-empty, only Teller
    accounts whose id is in that list are imported.
    """
    if not teller_client.is_configured():
        raise ValueError("Teller is not configured on this installation.")

    # Discover accounts from Teller
    teller_accounts = await teller_client.get_accounts(data.access_token)
    if not teller_accounts:
        raise ValueError(
            "No accounts returned from Teller. "
            "The enrollment may be invalid or the token has been revoked."
        )

    # Apply account_ids filter if provided
    if data.account_ids:
        teller_accounts = [a for a in teller_accounts if a.id in data.account_ids]

    # Resolve default Personal profile for this user
    profile_id: uuid.UUID | None = None
    profile_stmt = (
        select(BudgetProfile)
        .join(
            BudgetProfileMember,
            (BudgetProfileMember.profile_id == BudgetProfile.id) &
            (BudgetProfileMember.user_id == user_id),
        )
        .where(
            BudgetProfile.household_id == household_id,
            BudgetProfile.name == "Personal",
        )
        .limit(1)
    )
    profile_result = await db.execute(profile_stmt)
    personal_profile = profile_result.scalar_one_or_none()
    if personal_profile:
        profile_id = personal_profile.id

    created: list[BudgetAccountResponse] = []

    for ta in teller_accounts:
        # Check for existing account with this teller_account_id
        existing_stmt = select(BudgetAccount).where(
            BudgetAccount.household_id == household_id,
            BudgetAccount.teller_account_id == ta.id,
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing:
            # Re-authentication — update token and enrollment, preserve cursor
            existing.teller_enrollment_id = data.enrollment_id
            existing.teller_access_token = data.access_token
            existing.teller_institution_name = ta.institution_name
            existing.updated_at = datetime.now(timezone.utc)
            await db.flush()
            created.append(BudgetAccountResponse.model_validate(existing))
            continue

        # Derive a display name: "Chase Checking ••••1234"
        suffix = f" ••••{ta.last_four}" if ta.last_four else ""
        display_name = f"{ta.institution_name} {ta.subtype.replace('_', ' ').title()}{suffix}"

        account = BudgetAccount(
            household_id=household_id,
            owner_user_id=user_id,
            profile_id=profile_id,
            name=display_name,
            account_type=_teller_account_type(ta.type, ta.subtype),
            scope="personal",
            currency=ta.currency or "USD",
            teller_enrollment_id=data.enrollment_id,
            teller_access_token=data.access_token,
            teller_account_id=ta.id,
            teller_institution_name=ta.institution_name,
        )
        db.add(account)
        await db.flush()
        created.append(BudgetAccountResponse.model_validate(account))

    await db.commit()
    return created


async def sync_teller_account(
    db: AsyncSession,
    account: BudgetAccount,
) -> TellerSyncResult:
    """
    Poll Teller for new transactions on one linked account and import them.

    Uses teller_cursor as the from_id so only transactions newer than the
    last sync are fetched.  Updates teller_cursor and teller_last_synced_at
    after a successful import.

    Pending transactions (status != "posted") are skipped — Teller will
    include them as posted in a future sync once they settle.
    """
    if not account.teller_account_id or not account.teller_access_token:
        raise ValueError(f"Account {account.id} is not linked to Teller.")

    # First-ever sync (no cursor): paginate backwards through full history.
    # Subsequent syncs: single call with cursor to fetch only new transactions.
    if account.teller_cursor:
        transactions = await teller_client.get_transactions(
            access_token=account.teller_access_token,
            teller_account_id=account.teller_account_id,
            from_id=account.teller_cursor,
        )
    else:
        transactions = await teller_client.get_all_transactions(
            access_token=account.teller_access_token,
            teller_account_id=account.teller_account_id,
        )

    # Only import posted transactions; pending will reappear once settled
    posted = [t for t in transactions if t.status == "posted"]

    to_insert = [
        BudgetTransactionCreate(
            account_id=account.id,
            date=t.date,
            amount=t.amount,
            description=t.description,
            merchant_name=t.merchant_name,
            external_id=t.id,
            import_source="teller",  # type: ignore[arg-type]
            running_balance=t.running_balance,
        )
        for t in posted
    ]

    inserted = skipped = 0
    if to_insert:
        result = await bulk_import_transactions(
            db,
            account.household_id,
            account.id,
            "teller",
            to_insert,
        )
        inserted = result.inserted
        skipped = result.skipped

    # Advance cursor to the newest *posted* transaction ID only.
    # Never advance past a pending transaction: Teller's from_id filter returns
    # transactions *newer* than the stored ID, so if the cursor lands on a pending
    # ID that's later than any pending-that-settled IDs, those settled transactions
    # will be permanently skipped on future syncs.  Keeping the cursor at the last
    # posted ID means pending transactions are re-fetched each sync until they post.
    if posted:
        account.teller_cursor = posted[0].id

    # Fetch and store the current account balance
    balance = await teller_client.get_balance(
        access_token=account.teller_access_token,
        teller_account_id=account.teller_account_id,
    )
    if balance is not None and balance.ledger is not None:
        account.current_balance = balance.ledger
        account.balance_updated_at = datetime.now(timezone.utc)

    now = datetime.now(timezone.utc)
    account.teller_last_synced_at = now
    account.updated_at = now
    await db.commit()

    auto_categorized = 0
    if inserted > 0:
        auto_categorized = await auto_categorize_transactions(
            db, account.household_id, account_id=account.id
        )

    return TellerSyncResult(
        account_id=account.id,
        teller_account_id=account.teller_account_id,
        institution_name=account.teller_institution_name,
        inserted=inserted,
        skipped=skipped,
        auto_categorized=auto_categorized,
        last_synced_at=now,
    )


async def sync_all_teller_accounts(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> TellerSyncAllResult:
    """
    Sync all Teller-linked accounts for a household in sequence.
    Errors on individual accounts are logged and skipped so one bad
    enrollment doesn't block the rest.
    """
    stmt = select(BudgetAccount).where(
        BudgetAccount.household_id == household_id,
        BudgetAccount.teller_account_id.isnot(None),
        BudgetAccount.teller_access_token.isnot(None),
        BudgetAccount.archived_at.is_(None),
    )
    accounts = list((await db.execute(stmt)).scalars().all())

    results: list[TellerSyncResult] = []
    for account in accounts:
        try:
            result = await sync_teller_account(db, account)
            results.append(result)
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "Teller sync failed for account %s (%s): %s",
                account.id, account.name, exc,
            )

    return TellerSyncAllResult(
        accounts_synced=len(results),
        total_inserted=sum(r.inserted for r in results),
        total_skipped=sum(r.skipped for r in results),
        total_auto_categorized=sum(r.auto_categorized for r in results),
        results=results,
    )


async def sync_all_teller_accounts_globally() -> None:
    """
    Scheduler entry point: sync Teller-linked accounts for every household
    that has at least one active linked account.

    Opens its own DB session (same pattern as run_scheduled_digests) so this
    can be called from APScheduler without a request context.  Errors on
    individual households are logged and skipped so one bad enrollment doesn't
    block the rest.
    """
    import logging as _logging
    from life_dashboard.core.database import AsyncSessionLocal

    _log = _logging.getLogger(__name__)
    _log.info("Teller background sync starting")

    async with AsyncSessionLocal() as db:
        # Find all distinct household_ids that have at least one active
        # Teller-linked account.
        from sqlalchemy import distinct
        stmt = (
            select(distinct(BudgetAccount.household_id))
            .where(
                BudgetAccount.teller_account_id.isnot(None),
                BudgetAccount.teller_access_token.isnot(None),
                BudgetAccount.archived_at.is_(None),
            )
        )
        household_ids = list((await db.execute(stmt)).scalars().all())

    total_accounts = 0
    total_inserted = 0
    errors = 0

    for hid in household_ids:
        try:
            async with AsyncSessionLocal() as db:
                result = await sync_all_teller_accounts(db, hid)
                total_accounts += result.accounts_synced
                total_inserted += result.total_inserted
                _log.info(
                    "Teller sync household=%s accounts=%d inserted=%d",
                    hid, result.accounts_synced, result.total_inserted,
                )
        except Exception as exc:
            errors += 1
            _log.warning("Teller sync failed for household %s: %s", hid, exc)

    _log.info(
        "Teller background sync done: households=%d accounts=%d inserted=%d errors=%d",
        len(household_ids), total_accounts, total_inserted, errors,
    )


async def check_budget_thresholds(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> None:
    """
    For every active budget category with a monthly target, compute how much
    has been spent so far this calendar month.  When spending crosses 80% or
    100% of the target, dispatch a household-wide notification — once per
    threshold per category per month (deduped by notification type string).

    Designed to be called after each Teller sync.  Does NOT commit; the
    caller (sync_all_teller_accounts) owns the transaction.
    """
    from life_dashboard.domains.notifications.models import Notification
    from life_dashboard.auth.models import HouseholdMembership

    today = date_type.today()
    month_start = date_type(today.year, today.month, 1)
    month_end = date_type(today.year, today.month, calendar.monthrange(today.year, today.month)[1])

    # Fetch all categories with a target set
    cats_result = await db.execute(
        select(BudgetCategory).where(
            BudgetCategory.household_id == household_id,
            BudgetCategory.default_monthly_amount.isnot(None),
            BudgetCategory.archived_at.is_(None),
        )
    )
    categories = cats_result.scalars().all()
    if not categories:
        return

    # Sum spending per category for the current month (expenses = negative amounts)
    spend_rows = await db.execute(
        select(
            BudgetTransaction.category_id,
            func.sum(BudgetTransaction.amount).label("total"),
        ).where(
            BudgetTransaction.household_id == household_id,
            BudgetTransaction.date >= month_start,
            BudgetTransaction.date <= month_end,
            BudgetTransaction.is_transfer.is_(False),
            BudgetTransaction.category_id.isnot(None),
        ).group_by(BudgetTransaction.category_id)
    )
    spend_by_category: dict[uuid.UUID, float] = {
        row.category_id: float(row.total or 0)
        for row in spend_rows
    }

    # Fetch all household member IDs for dispatching
    member_ids = list(
        (await db.execute(
            select(HouseholdMembership.user_id).where(
                HouseholdMembership.household_id == household_id
            )
        )).scalars().all()
    )
    if not member_ids:
        return

    # Fetch existing budget threshold notifications this calendar month
    existing_notifs_result = await db.execute(
        select(Notification.type, Notification.entity_id).where(
            Notification.household_id == household_id,
            Notification.type.like("budget_threshold_%"),
            Notification.created_at >= datetime(today.year, today.month, 1, tzinfo=timezone.utc),
        )
    )
    # Set of (type, entity_id) tuples already dispatched this month
    dispatched: set[tuple[str, uuid.UUID]] = {
        (row.type, row.entity_id)
        for row in existing_notifs_result
    }

    for category in categories:
        # Skip categories where the user has disabled notifications
        if category.notify_threshold_pct is None:
            continue

        target = float(category.default_monthly_amount)
        if target <= 0:
            continue

        # Amounts are negative for expenses; flip sign to get positive spend
        raw_spend = spend_by_category.get(category.id, 0.0)
        spent = abs(raw_spend)
        pct = spent / target

        user_threshold = category.notify_threshold_pct / 100.0
        thresholds = []
        if pct >= 1.0:
            thresholds.append(("budget_threshold_100", 100))
        if pct >= user_threshold and user_threshold < 1.0:
            thresholds.append((f"budget_threshold_{category.notify_threshold_pct}", category.notify_threshold_pct))

        for notif_type, threshold_pct in thresholds:
            key = (notif_type, category.id)
            if key in dispatched:
                continue  # Already notified this month

            payload = {
                "category_name": category.name,
                "threshold_pct": threshold_pct,
                "spent": round(spent, 2),
                "target": round(target, 2),
                "title": (
                    f"{'Over' if threshold_pct == 100 else 'Approaching'} budget: {category.name}"
                ),
            }
            for member_id in member_ids:
                n = Notification(
                    household_id=household_id,
                    recipient_id=member_id,
                    actor_id=None,  # system-generated
                    type=notif_type,
                    entity_type="budget_category",
                    entity_id=category.id,
                    payload=payload,
                )
                db.add(n)
            dispatched.add(key)
