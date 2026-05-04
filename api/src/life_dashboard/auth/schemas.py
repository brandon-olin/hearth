import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    is_active: bool
    is_agent: bool
    last_login_at: datetime | None
    created_at: datetime


class TokenResponse(BaseModel):
    """Returned by /auth/refresh. The refresh token is delivered via httpOnly cookie, not here."""
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    """Returned by /auth/login. Includes the user so the frontend doesn't need a follow-up call."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
