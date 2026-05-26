import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.hashing import hash_password
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.tokens import create_access_token
from life_dashboard.core.database import get_db
from life_dashboard.core.permissions import (
    CONFIGURABLE_DOMAINS,
    merge_with_defaults,
    validate_permissions_config,
)
from life_dashboard.core.settings import settings

router = APIRouter(prefix="/households", tags=["households"])

_ADMIN_ROLES = {MembershipRole.owner, MembershipRole.admin}


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    display_name: str | None
    email: str
    role: str
    joined_at: datetime
    # ai-access-001: admin-controlled per-member gate for AI features.
    # True by default; admins can flip via PATCH /households/members/{user_id}.
    ai_features_enabled: bool = True


class UpdateMemberRequest(BaseModel):
    """Admin-only PATCH for member-level toggles.

    ai_features_enabled: gates the member's access to AI surfaces.
    Future room for role changes etc. — kept as a small open shape.
    """
    ai_features_enabled: bool | None = None


class UpdateHouseholdNameRequest(BaseModel):
    name: str


class AddMemberRequest(BaseModel):
    email: str
    display_name: str | None = None
    # Assignable roles: admin | member | viewer (owner/agent not allowed here)
    role: str = "member"


class HouseholdNameResponse(BaseModel):
    name: str


class ImpersonateResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    display_name: str | None


# ── Permissions schemas ───────────────────────────────────────────────────────

class DomainPermissions(BaseModel):
    """Per-domain action thresholds. Each value is a role name: owner | member | viewer."""
    read: str = "viewer"
    create: str = "viewer"
    manage_others: str = "member"


class HouseholdPermissionsResponse(BaseModel):
    """Fully-populated permissions config (defaults filled in) plus the domain metadata."""
    config: dict[str, DomainPermissions]
    domains: list[dict[str, str]]   # ordered list of {key, label, description}


class UpdatePermissionsRequest(BaseModel):
    config: dict[str, Any]


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MemberResponse]:
    """Return all active members of the current user's household."""
    result = await db.execute(
        select(
            User,
            HouseholdMembership.role,
            HouseholdMembership.joined_at,
            HouseholdMembership.ai_features_enabled,
        )
        .join(HouseholdMembership, User.id == HouseholdMembership.user_id)
        .where(
            HouseholdMembership.household_id == current_user.household_id,
            User.is_active == True,  # noqa: E712
        )
        .order_by(HouseholdMembership.joined_at.asc())
    )
    return [
        MemberResponse(
            user_id=user.id,
            display_name=user.display_name,
            email=user.email,
            role=role.value,
            joined_at=joined_at,
            ai_features_enabled=ai_features_enabled,
        )
        for user, role, joined_at, ai_features_enabled in result.all()
    ]


@router.patch("/members/{user_id}", response_model=MemberResponse)
async def update_member(
    user_id: uuid.UUID,
    body: UpdateMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemberResponse:
    """ai-access-001: admin-only PATCH for member-level toggles.

    Currently only ai_features_enabled is settable; future toggles
    can slot in. The admin cannot disable their OWN AI access through
    this endpoint to avoid lockouts (they'd need another admin to
    re-enable). Members managing their own AI off-switch can do so
    by clearing their API key in Settings → AI.
    """
    # Authorize: must be an owner or admin in the current household.
    actor_membership = (await db.execute(
        select(HouseholdMembership).where(
            HouseholdMembership.user_id == current_user.id,
            HouseholdMembership.household_id == current_user.household_id,
        )
    )).scalar_one_or_none()
    if actor_membership is None or actor_membership.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can modify household members.",
        )

    # Target membership must exist in this household.
    target_membership = (await db.execute(
        select(HouseholdMembership).where(
            HouseholdMembership.user_id == user_id,
            HouseholdMembership.household_id == current_user.household_id,
        )
    )).scalar_one_or_none()
    if target_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this household.",
        )

    sent = body.model_fields_set

    if "ai_features_enabled" in sent and body.ai_features_enabled is not None:
        # Guardrail: an admin can't lock themselves out of AI via this
        # endpoint. If they want to disable for themselves they can
        # clear their API key in Settings → AI; otherwise they'd be
        # stuck unable to re-enable until another admin intervenes.
        if user_id == current_user.id and body.ai_features_enabled is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "You can't disable your own AI features through admin "
                    "controls. Clear your API key in Settings → AI instead."
                ),
            )
        target_membership.ai_features_enabled = body.ai_features_enabled

    await db.commit()
    await db.refresh(target_membership)

    # Re-fetch the User row to assemble the full response shape.
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    return MemberResponse(
        user_id=user.id,
        display_name=user.display_name,
        email=user.email,
        role=target_membership.role.value,
        joined_at=target_membership.joined_at,
        ai_features_enabled=target_membership.ai_features_enabled,
    )


@router.patch("/name", response_model=HouseholdNameResponse)
async def update_household_name(
    body: UpdateHouseholdNameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HouseholdNameResponse:
    """Update the household name. Admin and owner only."""
    membership_result = await db.execute(
        select(HouseholdMembership).where(
            HouseholdMembership.user_id == current_user.id,
            HouseholdMembership.household_id == current_user.household_id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership is None or membership.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can rename the household.",
        )

    household_result = await db.execute(
        select(Household).where(Household.id == current_user.household_id)
    )
    household = household_result.scalar_one_or_none()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found.")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be blank.")

    household.name = name
    await db.commit()
    return HouseholdNameResponse(name=household.name)


@router.post("/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_member(
    body: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemberResponse:
    """
    Add a new member to the current household.

    Creates a new user account (password = "password") if the email is not
    already registered, then adds them to the household with the given role.

    Admin/owner only. Allowed roles: admin, member, viewer.
    """
    membership_result = await db.execute(
        select(HouseholdMembership).where(
            HouseholdMembership.user_id == current_user.id,
            HouseholdMembership.household_id == current_user.household_id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership is None or membership.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can add household members.",
        )

    allowed_roles = {"admin", "member", "viewer"}
    if body.role not in allowed_roles:
        raise HTTPException(
            status_code=422,
            detail=f"role must be one of: {', '.join(sorted(allowed_roles))}",
        )

    email = body.email.lower().strip()

    # Check if a user with this email already exists.
    existing_user_result = await db.execute(select(User).where(User.email == email))
    existing_user = existing_user_result.scalar_one_or_none()

    if existing_user:
        # Check if they're already in this household.
        existing_membership_result = await db.execute(
            select(HouseholdMembership).where(
                HouseholdMembership.user_id == existing_user.id,
                HouseholdMembership.household_id == current_user.household_id,
            )
        )
        if existing_membership_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This user is already a member of the household.",
            )
        new_user = existing_user
    else:
        # Create a new account with the default dev password.
        display = body.display_name or email.split("@")[0]
        new_user = User(
            email=email,
            password_hash=hash_password("password"),
            display_name=display,
            is_active=True,
        )
        db.add(new_user)
        await db.flush()

    role_enum = MembershipRole(body.role)
    new_membership = HouseholdMembership(
        household_id=current_user.household_id,
        user_id=new_user.id,
        role=role_enum,
    )
    db.add(new_membership)
    await db.commit()
    await db.refresh(new_membership)

    return MemberResponse(
        user_id=new_user.id,
        display_name=new_user.display_name,
        email=new_user.email,
        role=role_enum.value,
        joined_at=new_membership.joined_at,
    )


@router.post("/dev/impersonate/{target_user_id}", response_model=ImpersonateResponse)
async def impersonate(
    target_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImpersonateResponse:
    """
    DEV ONLY. Returns an access token for another member of the same household.

    Lets an admin test the app through a different user's perspective without
    needing to log in/out. Disabled in production environments.
    """
    if settings.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Impersonation is only available in development mode.",
        )

    membership_result = await db.execute(
        select(HouseholdMembership).where(
            HouseholdMembership.user_id == current_user.id,
            HouseholdMembership.household_id == current_user.household_id,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership is None or membership.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can use impersonation.",
        )

    # Verify target is in the same household.
    target_membership_result = await db.execute(
        select(HouseholdMembership).where(
            HouseholdMembership.user_id == target_user_id,
            HouseholdMembership.household_id == current_user.household_id,
        )
    )
    if target_membership_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404,
            detail="User not found in this household.",
        )

    target_result = await db.execute(select(User).where(User.id == target_user_id))
    target = target_result.scalar_one_or_none()
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail="User not found or inactive.")

    return ImpersonateResponse(
        access_token=create_access_token(str(target.id)),
        user_id=str(target.id),
        email=target.email,
        display_name=target.display_name,
    )


# ── Household permissions ─────────────────────────────────────────────────────

@router.get("/permissions", response_model=HouseholdPermissionsResponse)
async def get_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HouseholdPermissionsResponse:
    """Return the household's permission config (defaults filled in)."""
    result = await db.execute(
        select(Household.permissions_config).where(Household.id == current_user.household_id)
    )
    raw = result.scalar_one_or_none()
    merged = merge_with_defaults(raw)
    return HouseholdPermissionsResponse(
        config={domain: DomainPermissions(**actions) for domain, actions in merged.items()},
        domains=CONFIGURABLE_DOMAINS,
    )


@router.put("/permissions", response_model=HouseholdPermissionsResponse)
async def update_permissions(
    body: UpdatePermissionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HouseholdPermissionsResponse:
    """Update the household's permission config. Admin/owner only."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can change household permissions.",
        )

    try:
        validated = validate_permissions_config(body.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    household_result = await db.execute(
        select(Household).where(Household.id == current_user.household_id)
    )
    household = household_result.scalar_one_or_none()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found.")

    household.permissions_config = validated
    await db.commit()

    return HouseholdPermissionsResponse(
        config={domain: DomainPermissions(**actions) for domain, actions in validated.items()},
        domains=CONFIGURABLE_DOMAINS,
    )
