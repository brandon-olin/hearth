import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.hashing import hash_password, is_sentinel, needs_rehash, verify_password
from life_dashboard.auth.models import EmailVerificationCode, Household, HouseholdMembership, MembershipRole, PasswordResetToken, RefreshToken, User
from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class AuthenticationError(Exception):
    """Invalid credentials or inactive account."""


class TokenError(Exception):
    """Refresh token is missing, expired, or already revoked."""


class VerificationError(Exception):
    """OTP is invalid, expired, or already used."""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    """SHA-256 the raw token before storing so the DB value is useless if leaked."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _as_aware(dt: datetime) -> datetime:
    """Return a timezone-aware datetime, assuming UTC if the value is naive.

    SQLAlchemy / psycopg2 can return timezone-naive datetimes from a
    TIMESTAMP WITH TIME ZONE column depending on driver version and pg config.
    This normalises the value before any aware ↔ aware comparison.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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

    Handles one case only:

    NAS / existing install — sentinel users with password_hash='!' exist
    (created by the raw-SQL Phase-0 migration). Hash the bootstrap password
    and write it so those accounts become usable.

    Fresh installs (no users at all) are handled by the First-Run Setup Wizard
    at POST /setup. Bootstrap no longer auto-creates users on a blank database
    so that the wizard is always the entry point for new installations.
    """
    if not settings.bootstrap_password:
        return False

    # ── Sentinel users from NAS Phase-0 migration ─────────────────────────────
    result = await db.execute(select(User).where(User.password_hash == "!"))
    sentinel_users = result.scalars().all()
    if sentinel_users:
        new_hash = hash_password(settings.bootstrap_password)
        for user in sentinel_users:
            user.password_hash = new_hash
            logger.info("Bootstrap: password set for %s", user.email)
        await db.commit()
        return True

    return False


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
    if (
        token is None
        or token.revoked_at is not None
        or _as_aware(token.expires_at) <= now
    ):
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


# ── Email verification ────────────────────────────────────────────────────────

_CODE_TTL_MINUTES = 15
_CODE_LENGTH = 6  # 6-digit numeric OTP → 1,000,000 possibilities


def _generate_otp() -> str:
    """Return a cryptographically random 6-digit string (zero-padded)."""
    return f"{secrets.randbelow(10 ** _CODE_LENGTH):0{_CODE_LENGTH}d}"


async def create_verification_code(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Generate a 6-digit OTP, persist its hash, and return the raw code.

    Any previous unused codes for this user are implicitly superseded (not
    deleted — they'll fail to verify because we check used_at and expiry).
    """
    raw_code = _generate_otp()
    db.add(EmailVerificationCode(
        user_id=user_id,
        code_hash=_hash_token(raw_code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES),
    ))
    await db.commit()
    return raw_code


async def verify_email_code(db: AsyncSession, user_id: uuid.UUID, raw_code: str) -> None:
    """Validate the OTP and mark the user's email as verified.

    Raises VerificationError on any failure (wrong code, expired, already used).
    Uses a constant error message to avoid leaking which check failed.
    """
    _INVALID = "Verification code is invalid or has expired."

    result = await db.execute(
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.user_id == user_id,
            EmailVerificationCode.code_hash == _hash_token(raw_code),
        )
    )
    record = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if record is None or record.used_at is not None or _as_aware(record.expires_at) <= now:
        raise VerificationError(_INVALID)

    # Mark code as consumed and user as verified in one transaction.
    record.used_at = now

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise VerificationError(_INVALID)

    user.email_verified = True
    user.last_login_at = now
    await db.commit()


# ── Password reset ───────────────────────────────────────────────────────────

_RESET_TTL_HOURS = 1


class PasswordResetError(Exception):
    """Reset token is invalid, expired, or already used."""


async def create_password_reset_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Generate a URL-safe reset token, store its hash, and return the raw value.

    Any previous unused tokens for this user remain in the table but will fail
    validation once this new one is issued (latest token wins is fine here since
    each token is independently validated against its hash).
    """
    raw = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        user_id=user_id,
        token_hash=_hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=_RESET_TTL_HOURS),
    ))
    await db.commit()
    return raw


async def consume_password_reset_token(
    db: AsyncSession, raw_token: str, new_password: str
) -> User:
    """Validate the reset token, set the new password, and return the updated user.

    Raises PasswordResetError on any failure (invalid, expired, already used).
    Also clears force_password_change if it was set.
    """
    _INVALID = "Password reset link is invalid or has expired."

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash_token(raw_token)
        )
    )
    token = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if token is None or token.used_at is not None or _as_aware(token.expires_at) <= now:
        raise PasswordResetError(_INVALID)

    user = await get_user_by_id(db, token.user_id)
    if user is None or not user.is_active:
        raise PasswordResetError(_INVALID)

    token.used_at = now
    user.password_hash = hash_password(new_password)
    user.force_password_change = False
    await db.commit()
    await db.refresh(user)
    return user


# ── Account deletion ──────────────────────────────────────────────────────────

async def delete_account(db: AsyncSession, user: User, password: str) -> None:
    """
    Permanently deletes a user account and all data they solely own.

    Steps:
      1. Verify the supplied password — raises AuthenticationError on mismatch.
      2. For each household where this user is a member:
           • Sole member  → delete the household.
             The DB CASCADE on household_id propagates to every domain table
             (todos, projects, habits, goals, documents, notes, workouts, …).
           • Shared (other members exist) → delete only this user's membership.
             Household data is preserved for the remaining members.
      3. Delete the user record.
         The DB CASCADE on user_id propagates to refresh_tokens and ai_usage.

    This is intentionally irreversible and has no soft-delete fallback.
    """
    if is_sentinel(user.password_hash) or not verify_password(password, user.password_hash):
        raise AuthenticationError("Incorrect password.")

    # Load memberships with a count of co-members for each household.
    memberships_result = await db.execute(
        select(HouseholdMembership).where(HouseholdMembership.user_id == user.id)
    )
    memberships = memberships_result.scalars().all()

    for membership in memberships:
        # Count all members of this household (including the user being deleted).
        count_result = await db.execute(
            select(func.count())
            .select_from(HouseholdMembership)
            .where(HouseholdMembership.household_id == membership.household_id)
        )
        member_count = count_result.scalar_one()

        if member_count == 1:
            # Sole member — delete the household; DB cascade handles all data.
            household_result = await db.execute(
                select(Household).where(Household.id == membership.household_id)
            )
            household = household_result.scalar_one_or_none()
            if household:
                await db.delete(household)
                logger.info(
                    "delete_account: deleted household %s (sole member was user %s)",
                    household.id,
                    user.id,
                )
        else:
            # Shared household — remove only this user's membership.
            await db.delete(membership)
            logger.info(
                "delete_account: removed user %s from shared household %s",
                user.id,
                membership.household_id,
            )

    # Flush household deletes before removing the user to satisfy FK constraints
    # on any tables that reference both household_id and user_id.
    await db.flush()

    await db.delete(user)
    await db.commit()
    logger.info("delete_account: user %s permanently deleted", user.id)
