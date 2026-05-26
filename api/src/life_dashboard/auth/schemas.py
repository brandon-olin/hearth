import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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
