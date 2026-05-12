"""
First-run setup endpoints.

These are intentionally public (no auth required) and are the only way to
create the very first household + admin account when there are no users yet.

Once any user exists, POST /setup returns 409 Conflict so it cannot be used
as an unauthenticated account-creation endpoint.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.hashing import hash_password
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.schemas import LoginResponse, UserResponse
from life_dashboard.auth.service import create_refresh_token
from life_dashboard.auth.tokens import create_access_token
from life_dashboard.core.database import get_db
from life_dashboard.core.settings import settings
from life_dashboard.domains.projects.service import seed_system_project

router = APIRouter(prefix="/setup", tags=["setup"])

_COOKIE_NAME = "refresh_token"
_COOKIE_MAX_AGE = settings.refresh_token_expire_days * 24 * 60 * 60
_COOKIE_SECURE = settings.environment != "development"


# ── Schemas ───────────────────────────────────────────────────────────────────

class SetupStatusResponse(BaseModel):
    needs_setup: bool


class SetupRequest(BaseModel):
    display_name: str
    email: str
    password: str
    household_name: str
    # Preferences are written straight to the user row so the PreferencesSyncer
    # picks them up on first login without an extra round-trip.
    preferences: dict[str, Any] | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )


async def _user_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=SetupStatusResponse)
async def setup_status(db: AsyncSession = Depends(get_db)) -> SetupStatusResponse:
    """
    Public. Returns needs_setup=True when no users exist.
    The frontend calls this on every load to decide whether to show the wizard.
    """
    return SetupStatusResponse(needs_setup=await _user_count(db) == 0)


@router.post("", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def complete_setup(
    body: SetupRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Public. Creates the first household + admin user, seeds the system project,
    and returns a LoginResponse so the frontend can log the user in immediately.

    Returns 409 Conflict once any user exists.
    """
    if await _user_count(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has already been completed. Use /auth/login to sign in.",
        )

    # Household
    household = Household(name=body.household_name)
    db.add(household)
    await db.flush()

    # Admin user
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        is_active=True,
        preferences=body.preferences,
    )
    db.add(user)
    await db.flush()

    db.add(HouseholdMembership(
        household_id=household.id,
        user_id=user.id,
        role=MembershipRole.owner,
    ))
    await db.flush()

    # Seed default system project (Inbox / To-dos)
    await seed_system_project(db, household_id=household.id, user_id=user.id)

    await db.commit()
    await db.refresh(user)

    # Issue tokens — user is logged in immediately after setup
    raw_refresh = await create_refresh_token(
        db, user.id, request.headers.get("User-Agent")
    )
    _set_refresh_cookie(response, raw_refresh)

    return LoginResponse(
        access_token=create_access_token(str(user.id)),
        user=UserResponse.model_validate(user),
    )
