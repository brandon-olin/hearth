import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import HouseholdMembership, User
from life_dashboard.auth.service import get_user_by_id
from life_dashboard.auth.tokens import JWTError, decode_access_token
from life_dashboard.core.database import get_db


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency — resolves a Bearer token to a User.

    Also loads the user's household membership and attaches household_id
    as a Python attribute so domain routers can use current_user.household_id
    without an extra query.

    Import and use as `Depends(get_current_user)` in any protected route.
    Raises 401 if the token is absent, malformed, expired, or the user is inactive.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = auth_header.removeprefix("Bearer ")
    try:
        payload = decode_access_token(raw_token)
        subject: str | None = payload.get("sub")
        if not subject:
            raise JWTError("missing sub claim")
        user_id = uuid.UUID(subject)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(HouseholdMembership).where(HouseholdMembership.user_id == user_id)
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no household membership",
        )

    # Attach as a plain Python attribute — not an ORM column, never written to DB.
    user.household_id = membership.household_id  # type: ignore[attr-defined]
    return user
