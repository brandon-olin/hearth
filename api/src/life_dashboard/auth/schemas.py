import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    household_name: str | None = None
    role: str | None = None
    is_active: bool
    is_agent: bool
    last_login_at: datetime | None
    preferences: dict[str, Any] | None
    # Locale settings — auto-detected from browser on first login, user-overridable
    timezone: str | None = None
    date_format: str | None = None
    week_start: str | None = None
    created_at: datetime
    # ai-access-001: per-membership AI gate. True for accounts created
    # before this feature shipped (the server default backfills them).
    # Frontend hides AI surfaces when False.
    ai_features_enabled: bool = True
    # invite-001: True when an admin created this account on the user's behalf.
    # The frontend blocks app access and shows a "set your password" screen.
    # Cleared once the user sets their own password.
    force_password_change: bool = False


class UpdateMeRequest(BaseModel):
    display_name: str | None = None
    preferences: dict[str, Any] | None = None
    # Locale settings
    timezone: str | None = None
    date_format: str | None = None
    week_start: str | None = None


class ChangePasswordRequest(BaseModel):
    """Requires the current password to authorise the change."""
    current_password: str
    new_password: str


class DeleteMeRequest(BaseModel):
    """Password confirmation is required to prevent accidental account deletion."""
    password: str


class TokenResponse(BaseModel):
    """Returned by /auth/refresh. The refresh token is delivered via httpOnly cookie, not here."""
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    """Returned by /auth/login. Includes the user so the frontend doesn't need a follow-up call."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class RegistrationPendingResponse(BaseModel):
    """Returned by /auth/register when email verification is required.

    The frontend should redirect to the verify-email page, passing user_id
    so the verify endpoint knows whose code to check.
    """
    needs_verification: bool = True
    user_id: str
    email: str  # displayed in the "we sent a code to …" UI


class VerifyEmailRequest(BaseModel):
    user_id: uuid.UUID
    code: str  # raw 6-digit OTP as entered by the user


class ResendVerificationRequest(BaseModel):
    email: str


# ── Password reset ────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    # When True the endpoint issues login tokens and returns LoginResponse instead
    # of 204. Used by the accept-invite flow to skip the redundant login step.
    auto_login: bool = False


class SetInitialPasswordRequest(BaseModel):
    """Used by newly invited users who have force_password_change=True."""
    new_password: str


# ── Personal access tokens (security-006) ─────────────────────────────────────

class PATCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # { "<domain>": "read" | "write" } — validated against the vocabulary in
    # auth/pat_scopes.py, which returns a 422 listing the valid values.
    scopes: dict[str, str]
    # None = never expires (Home Assistant-style long-lived token).
    expires_in_days: int | None = Field(default=365, ge=1, le=3650)


class PATResponse(BaseModel):
    """A token's non-secret metadata. Deliberately has no token/secret field —
    the plaintext exists only in PATCreateResponse, once, at creation."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    scopes: dict[str, str]
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class PATCreateResponse(BaseModel):
    """Returned once by POST /auth/tokens. `token` is unrecoverable afterwards —
    only its hash is stored."""
    token: str
    pat: PATResponse


class PATScopeOption(BaseModel):
    """One selectable scope domain, for building the token-creation UI."""
    key: str
    label: str
