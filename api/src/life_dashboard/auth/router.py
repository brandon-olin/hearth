from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.auth.schemas import LoginRequest, LoginResponse, TokenResponse, UserResponse
from life_dashboard.auth.service import (
    AuthenticationError,
    TokenError,
    authenticate_user,
    create_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from life_dashboard.auth.tokens import create_access_token
from life_dashboard.core.database import get_db
from life_dashboard.core.settings import settings

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
        path="/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_COOKIE_NAME,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/auth",
    )


@router.post("/login", response_model=LoginResponse)
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
