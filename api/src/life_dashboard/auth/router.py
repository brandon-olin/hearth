import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from life_dashboard.core.rate_limit import limiter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.email import EmailSendError, send_verification_email
from life_dashboard.auth.hashing import hash_password
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, User
from life_dashboard.auth.schemas import (
    ChangePasswordRequest,
    DeleteMeRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegistrationPendingResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SetInitialPasswordRequest,
    TokenResponse,
    UpdateMeRequest,
    UserResponse,
    VerifyEmailRequest,
)
from life_dashboard.auth.service import (
    AuthenticationError,
    PasswordResetError,
    TokenError,
    VerificationError,
    authenticate_user,
    consume_password_reset_token,
    create_password_reset_token,
    create_refresh_token,
    create_verification_code,
    delete_account,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_email_code,
)
from life_dashboard.auth.tokens import create_access_token
from life_dashboard.core.database import get_db
from life_dashboard.core.settings import settings
from life_dashboard.domains.projects.service import seed_system_project
from sqlalchemy import select

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"
_COOKIE_MAX_AGE = settings.refresh_token_expire_days * 24 * 60 * 60  # seconds
# Secure flag requires HTTPS — disable in local dev where the server runs over HTTP.
_COOKIE_SECURE = settings.environment != "development"


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


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_COOKIE_NAME,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=RegistrationPendingResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/hour")
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> RegistrationPendingResponse:
    """
    Public. Creates a new household + account and sends a 6-digit OTP to the
    provided email address.  Does NOT issue a session — the client must call
    POST /auth/verify-email with the OTP to complete login.

    display_name defaults to the local part of the email address.
    household_name defaults to "{display_name}'s Home".
    Password must be at least 8 characters.

    Returns 409 Conflict if the email is already registered.
    Returns 503 if the email service is unavailable.
    """
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters.",
        )

    email = body.email.lower().strip()

    # Check for duplicate email.
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    display_name = email.split("@")[0]
    household_name = f"{display_name}'s Home"

    household = Household(name=household_name)
    db.add(household)
    await db.flush()

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=display_name,
        is_active=True,
        email_verified=False,
        # Flag consumed by the frontend to trigger the post-registration
        # onboarding wizard (household name, theme, nav).  Flipped to True
        # when the user completes /onboarding.
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

    # Generate OTP and send verification email.
    raw_code = await create_verification_code(db, user.id)
    try:
        await send_verification_email(email, raw_code)
    except EmailSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    return RegistrationPendingResponse(user_id=str(user.id), email=email)


@router.post("/verify-email", response_model=LoginResponse)
@limiter.limit("5/15minute")
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Submit the 6-digit OTP emailed at registration to complete account setup.

    On success: marks the email verified, issues access + refresh tokens, and
    returns a full LoginResponse so the client can enter the app immediately.

    Rate-limited to 5 attempts per 15 minutes to resist brute-force on the
    OTP space.  Returns 400 on any invalid/expired/used code (generic message).
    """
    try:
        await verify_email_code(db, body.user_id, body.code.strip())
    except VerificationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Reload user with household info (same pattern as login).
    user_result = await db.execute(select(User).where(User.id == body.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found.")

    membership_result = await db.execute(
        select(HouseholdMembership).where(HouseholdMembership.user_id == user.id)
    )
    membership = membership_result.scalar_one_or_none()
    if membership:
        household_result = await db.execute(
            select(Household).where(Household.id == membership.household_id)
        )
        household = household_result.scalar_one_or_none()
        user.household_name = household.name if household else None  # type: ignore[attr-defined]
        user.role = membership.role.value  # type: ignore[attr-defined]
    else:
        user.household_name = None  # type: ignore[attr-defined]
        user.role = None  # type: ignore[attr-defined]

    raw_refresh = await create_refresh_token(db, user.id, request.headers.get("User-Agent"))
    _set_refresh_cookie(response, raw_refresh)

    return LoginResponse(
        access_token=create_access_token(str(user.id)),
        user=UserResponse.model_validate(user),
    )


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/hour")
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Resend a verification OTP to the given email address.

    Always returns 204 regardless of whether the email exists or is already
    verified — this prevents email enumeration.  Rate-limited to 3/hour.
    """
    email = body.email.lower().strip()
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()

    # Silently no-op for unknown emails or already-verified accounts.
    if user is None or user.email_verified:
        return

    raw_code = await create_verification_code(db, user.id)
    try:
        await send_verification_email(email, raw_code)
    except EmailSendError:
        # Don't expose the failure — log it server-side and return 204 anyway.
        # The user can try again; a 503 here would leak that the email was found.
        pass


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    try:
        user = await authenticate_user(db, body.email, body.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    # Attach household_name so UserResponse can include it (same pattern as get_current_user).
    membership_result = await db.execute(
        select(HouseholdMembership).where(HouseholdMembership.user_id == user.id)
    )
    membership = membership_result.scalar_one_or_none()
    if membership:
        household_result = await db.execute(
            select(Household).where(Household.id == membership.household_id)
        )
        household = household_result.scalar_one_or_none()
        user.household_name = household.name if household else None  # type: ignore[attr-defined]
        user.role = membership.role.value  # type: ignore[attr-defined]

    raw_refresh = await create_refresh_token(db, user.id, request.headers.get("User-Agent"))
    _set_refresh_cookie(response, raw_refresh)

    return LoginResponse(
        access_token=create_access_token(str(user.id)),
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    try:
        new_raw, user = await rotate_refresh_token(db, refresh_token, request.headers.get("User-Agent"))
    except TokenError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    _set_refresh_cookie(response, new_raw)
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
) -> None:
    if refresh_token:
        await revoke_refresh_token(db, refresh_token)
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Change the authenticated user's password.

    Requires the current password for verification. The new password must be
    at least 8 characters. All existing refresh tokens remain valid — the user
    stays logged in on all devices (intentional; add token revocation later if needed).
    """
    from life_dashboard.auth.hashing import verify_password, is_sentinel
    from life_dashboard.auth.service import AuthenticationError

    if is_sentinel(current_user.password_hash) or not verify_password(
        body.current_password, current_user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect.",
        )
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 8 characters.",
        )
    current_user.password_hash = hash_password(body.new_password)
    await db.commit()


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    body: DeleteMeRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    refresh_token: str | None = Cookie(default=None),
) -> None:
    """
    Permanently deletes the authenticated user's account and all data they
    solely own. Requires password confirmation to prevent accidental deletion.

    Shared households (where other members exist) are preserved — only the
    user's membership is removed.
    """
    try:
        await delete_account(db, current_user, body.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    # Clear the auth cookie so the browser doesn't attempt a refresh.
    _clear_refresh_cookie(response)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/hour")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Request a password reset email.

    Always returns 204 regardless of whether the email exists — prevents
    email enumeration. Only sends the email on the cloud deployment tier;
    on local/self_hosted the response is still 204 but no email is sent
    (admins reset passwords by re-inviting or using impersonation).
    """
    from life_dashboard.auth.email import EmailSendError, send_password_reset_email

    email = body.email.lower().strip()
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()

    # Silently no-op for unknown emails or non-cloud tiers.
    if user is None or settings.deployment_tier != "cloud":
        return

    raw_token = await create_password_reset_token(db, user.id)

    # Build the reset URL from the request origin.
    origin = request.headers.get("origin") or settings.allowed_origins.split(",")[0].strip()
    reset_url = f"{origin}/reset-password?token={raw_token}"

    try:
        await send_password_reset_email(email, reset_url)
    except EmailSendError:
        # Don't expose the failure — return 204 so the UI shows "check your email".
        pass


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/hour")
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Consume a password reset token and set a new password.

    Returns 400 if the token is invalid, expired, or already used.
    Returns 422 if the new password is too short.
    """
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 8 characters.",
        )
    try:
        await consume_password_reset_token(db, body.token, body.new_password)
    except PasswordResetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/me/set-initial-password", status_code=status.HTTP_204_NO_CONTENT)
async def set_initial_password(
    body: SetInitialPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Set a new password for accounts with force_password_change=True.

    Used by newly invited household members on their first login — they
    don't know their old password (the admin never shared it on cloud tier),
    so this endpoint requires only authentication (active session) and the
    new password.

    Returns 403 if force_password_change is not set — use PATCH /auth/me/password
    for voluntary password changes on established accounts.
    """
    if not current_user.force_password_change:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Use PATCH /auth/me/password to change your password.",
        )
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 8 characters.",
        )
    current_user.password_hash = hash_password(body.new_password)
    current_user.force_password_change = False
    await db.commit()


_VALID_DATE_FORMATS = {"MM/DD/YY", "DD/MM/YYYY", "YYYY-MM-DD"}
_VALID_WEEK_STARTS = {"sunday", "monday"}


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: UpdateMeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    if body.display_name is not None:
        current_user.display_name = body.display_name
    if body.preferences is not None:
        # Merge rather than replace so clients can update individual keys
        # (e.g. a theme PATCH doesn't clobber a concurrent sidebar PATCH).
        existing = current_user.preferences or {}
        current_user.preferences = {**existing, **body.preferences}
        # SQLAlchemy doesn't always detect JSONB mutations when the dict
        # reference changes; flag_modified ensures the column is flushed.
        flag_modified(current_user, "preferences")
    # Locale settings — validated before persisting
    if body.timezone is not None:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(body.timezone)  # raises KeyError if invalid
        except (ImportError, KeyError):
            raise HTTPException(
                status_code=422,
                detail=f"Unknown timezone: {body.timezone!r}",
            )
        current_user.timezone = body.timezone
    if body.date_format is not None:
        if body.date_format not in _VALID_DATE_FORMATS:
            raise HTTPException(
                status_code=422,
                detail=f"date_format must be one of: {', '.join(sorted(_VALID_DATE_FORMATS))}",
            )
        current_user.date_format = body.date_format
    if body.week_start is not None:
        if body.week_start not in _VALID_WEEK_STARTS:
            raise HTTPException(
                status_code=422,
                detail=f"week_start must be one of: {', '.join(sorted(_VALID_WEEK_STARTS))}",
            )
        current_user.week_start = body.week_start
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)
