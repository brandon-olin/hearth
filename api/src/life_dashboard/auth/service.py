import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.hashing import hash_password, is_sentinel, needs_rehash, verify_password
from life_dashboard.auth.models import Household, HouseholdMembership, MembershipRole, RefreshToken, User
from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class AuthenticationError(Exception):
    """Invalid credentials or inactive account."""


class TokenError(Exception):
    """Refresh token is missing, expired, or already revoked."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    """SHA-256 the raw token before storing so the DB value is useless if leaked."""
    return hashlib.sha256(raw.encode()).hexdigest()


# ── User lookups ──────────────────────────────────────────────────────────────

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


# ── Bootstrap ─────────────────────────────────────────────────────────────────

async def run_bootstrap_if_needed(db: AsyncSession) -> bool:
    """Called at startup. Returns True if bootstrap was performed.

    Two cases:

    1. NAS / existing install — sentinel users with password_hash='!' exist
       (created by the raw-SQL Phase-0 migration). Hash the bootstrap password
       and write it so those accounts become usable.

    2. Fresh install — no users exist at all (Alembic baseline didn't seed any).
       Create a default household and owner account using BOOTSTRAP_PASSWORD,
       BOOTSTRAP_EMAIL, and BOOTSTRAP_DISPLAY_NAME from the environment.
    """
    if not settings.bootstrap_password:
        return False

    # ── Case 1: sentinel users from NAS Phase-0 migration ─────────────────────
    result = await db.execute(select(User).where(User.password_hash == "!"))
    sentinel_users = result.scalars().all()
    if sentinel_users:
        new_hash = hash_password(settings.bootstrap_password)
        for user in sentinel_users:
            user.password_hash = new_hash
            logger.info("Bootstrap: password set for %s", user.email)
        await db.commit()
        return True

    # ── Case 2: fresh install with no users at all ────────────────────────────
    count_result = await db.execute(select(func.count()).select_from(User))
    if count_result.scalar_one() > 0:
        # Real users exist — nothing to bootstrap.
        return False

    household = Household(name="My Household")
    db.add(household)
    await db.flush()  # populate household.id before referencing it

    user = User(
        email=settings.bootstrap_email,
        password_hash=hash_password(settings.bootstrap_password),
        display_name=settings.bootstrap_display_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()  # populate user.id before referencing it

    db.add(HouseholdMembership(
        household_id=household.id,
        user_id=user.id,
        role=MembershipRole.owner,
    ))
    await db.commit()
    logger.info(
        "Bootstrap: created household '%s' and owner account %s",
        household.name,
        settings.bootstrap_email,
    )
    return True


# ── Authentication ────────────────────────────────────────────────────────────

async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    """Verifies credentials and returns the User. Raises AuthenticationError on any failure.

    Uses a constant error message for all failure cases to avoid leaking whether
    an email address exists in the system.
    """
    user = await get_user_by_email(db, email)
    _INVALID = "Invalid email or password"

    if user is None or not user.is_active:
        raise AuthenticationError(_INVALID)
    if is_sentinel(user.password_hash):
        # Bootstrap did not run — BOOTSTRAP_PASSWORD was not set at startup.
        raise AuthenticationError("Account not yet activated. Set BOOTSTRAP_PASSWORD and restart.")
    if not verify_password(password, user.password_hash):
        raise AuthenticationError(_INVALID)

    # Silently upgrade the hash if argon2 parameters have changed since it was stored.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


# ── Refresh tokens ────────────────────────────────────────────────────────────

async def create_refresh_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_agent: str | None,
) -> str:
    """Generates a raw refresh token, stores its hash, and returns the raw value."""
    raw = secrets.token_urlsafe(32)
    db.add(RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(raw),
        user_agent=user_agent,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    ))
    await db.commit()
    return raw


async def rotate_refresh_token(
    db: AsyncSession,
    raw_token: str,
    user_agent: str | None,
) -> tuple[str, User]:
    """Validates the incoming token, revokes it, and atomically issues a replacement.

    The revocation and new-token creation happen in a single commit so there is
    no window where both tokens are simultaneously valid.
    Raises TokenError if the token is unknown, expired, or already revoked.
    """
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw_token))
    )
    token = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if token is None or token.revoked_at is not None or token.expires_at <= now:
        raise TokenError("Refresh token is invalid or has expired")

    user = await get_user_by_id(db, token.user_id)
    if user is None or not user.is_active:
        raise TokenError("Associated user not found or is inactive")

    # Revoke old token and create the replacement in one transaction.
    token.revoked_at = now
    new_raw = secrets.token_urlsafe(32)
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(new_raw),
        user_agent=user_agent,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    ))
    await db.commit()
    return new_raw, user


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> None:
    """Marks the token revoked. No-ops silently if not found (idempotent logout)."""
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw_token))
    )
    token = result.scalar_one_or_none()
    if token and token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        await db.commit()
