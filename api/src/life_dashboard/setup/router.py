"""
First-run setup endpoints.

These are intentionally public (no auth required) and are the only way to
create the very first household + admin account when there are no users yet.

Once any user exists, POST /setup returns 409 Conflict so it cannot be used
as an unauthenticated account-creation endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.email import EmailSendError, send_verification_email
from life_dashboard.auth.hashing import hash_password
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.schemas import RegistrationPendingResponse
from life_dashboard.auth.service import create_verification_code
from life_dashboard.core.database import get_db
from life_dashboard.domains.projects.service import seed_system_project

router = APIRouter(prefix="/setup", tags=["setup"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SetupStatusResponse(BaseModel):
    needs_setup: bool


class SetupRequest(BaseModel):
    display_name: str
    email: str
    password: str


# ── Helpers ───────────────────────────────────────────────────────────────────

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


@router.post("", response_model=RegistrationPendingResponse, status_code=status.HTTP_201_CREATED)
async def complete_setup(
    body: SetupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RegistrationPendingResponse:
    """
    Public. Creates the first household + admin user, seeds the system project,
    sends a verification email, and returns a RegistrationPendingResponse.

    The client must call POST /auth/verify-email with the OTP to get a session.
    After verification the client is redirected to /onboarding for household
    name, theme, and nav customization.

    Returns 409 Conflict once any user exists.
    Returns 503 if the email service is unavailable.
    """
    if await _user_count(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has already been completed. Use /auth/login to sign in.",
        )

    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters.",
        )

    email = body.email.lower().strip()

    # Household — default name, user will rename it in /onboarding
    display_name = body.display_name.strip() or email.split("@")[0]
    household = Household(name=f"{display_name}'s Home")
    db.add(household)
    await db.flush()

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=display_name,
        is_active=True,
        email_verified=False,
        preferences={"onboarding_completed": False},
    )
    db.add(user)
    await db.flush()

    db.add(HouseholdMembership(
        household_id=household.id,
        user_id=user.id,
        role=MembershipRole.owner,
    ))
    await db.flush()

    await seed_system_project(db, household_id=household.id, user_id=user.id)
    from life_dashboard.domains.collections.service import seed_default_journal_collection
    await seed_default_journal_collection(db, household_id=household.id, user_id=user.id)
    await db.commit()
    await db.refresh(user)

    # Send verification email — same OTP flow as /auth/register
    raw_code = await create_verification_code(db, user.id)
    try:
        await send_verification_email(email, raw_code)
    except EmailSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    return RegistrationPendingResponse(user_id=str(user.id), email=email)
