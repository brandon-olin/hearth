"""
Personal Access Token service (security-006).

All PAT database access lives here — routers and the auth dependency call
these functions and never touch the ORM directly.

Convention note: like the rest of auth/service.py, these functions return None
rather than raising HTTPException. Only routers and the dependency translate a
None into an HTTP status.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import PersonalAccessToken
from life_dashboard.auth.pat_scopes import PAT_TOKEN_PREFIX, validate_scopes

logger = logging.getLogger(__name__)

#: Number of random bytes behind each token. 32 bytes = 256 bits — brute force
#: is not a consideration at this size, which is what lets us store a fast hash.
_TOKEN_BYTES = 32

#: Characters of the secret kept in the non-secret `prefix` display column.
#: 8 chars is enough to tell tokens apart in the UI and far too few to guess
#: the remaining ~35 characters from.
_PREFIX_SECRET_CHARS = 8

#: last_used_at is refreshed at most this often. An agent polling every few
#: seconds would otherwise turn every read into a write; minute granularity is
#: all the management UI shows.
_LAST_USED_THROTTLE_SECONDS = 60

#: Cap on tokens per member — a bounded list keeps the management UI honest and
#: stops a runaway script from filling the table.
MAX_TOKENS_PER_USER = 50


class PATError(Exception):
    """Token could not be created — invalid scopes, bad expiry, or at the limit."""


def _hash_token(raw: str) -> str:
    """SHA-256 the raw token before storing so the DB value is useless if leaked."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _as_aware(dt: datetime) -> datetime:
    """Return a timezone-aware datetime, assuming UTC if the value is naive.

    Mirrors auth/service.py._as_aware — SQLAlchemy can hand back naive
    datetimes from a TIMESTAMP WITH TIME ZONE column depending on the driver.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def create_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    scopes: dict,
    expires_in_days: int | None,
) -> tuple[PersonalAccessToken, str]:
    """Create a PAT and return (record, raw_token).

    The raw token is returned to the caller exactly once and never persisted —
    only its hash is stored. Raises PATError on invalid input.
    """
    try:
        normalised_scopes = validate_scopes(scopes)
    except ValueError as exc:
        raise PATError(str(exc)) from exc

    if expires_in_days is not None and expires_in_days < 1:
        raise PATError("expires_in_days must be at least 1, or null for no expiry")

    count_result = await db.execute(
        select(PersonalAccessToken.id).where(
            PersonalAccessToken.user_id == user_id,
            PersonalAccessToken.revoked_at.is_(None),
        )
    )
    if len(count_result.scalars().all()) >= MAX_TOKENS_PER_USER:
        raise PATError(
            f"Token limit reached ({MAX_TOKENS_PER_USER} active tokens). "
            "Revoke an existing token first."
        )

    secret = secrets.token_urlsafe(_TOKEN_BYTES)
    raw_token = f"{PAT_TOKEN_PREFIX}{secret}"

    token = PersonalAccessToken(
        user_id=user_id,
        name=name,
        token_hash=_hash_token(raw_token),
        prefix=f"{PAT_TOKEN_PREFIX}{secret[:_PREFIX_SECRET_CHARS]}",
        scopes=normalised_scopes,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        ),
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    # Log the id and prefix only — never the secret.
    logger.info("PAT created: id=%s prefix=%s user=%s", token.id, token.prefix, user_id)
    return token, raw_token


async def list_tokens(db: AsyncSession, user_id: uuid.UUID) -> list[PersonalAccessToken]:
    """All non-revoked tokens for a member, newest first.

    Revoked tokens are excluded rather than soft-shown — once revoked a token
    is dead and listing it only clutters the UI.
    """
    result = await db.execute(
        select(PersonalAccessToken)
        .where(
            PersonalAccessToken.user_id == user_id,
            PersonalAccessToken.revoked_at.is_(None),
        )
        .order_by(PersonalAccessToken.created_at.desc())
        .limit(MAX_TOKENS_PER_USER)
    )
    return list(result.scalars().all())


async def revoke_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> bool:
    """Revoke a token. Returns False if it doesn't exist or isn't this user's.

    Scoped by user_id in the same statement as the id lookup — a member can
    never revoke another member's token by guessing its UUID (IDOR).

    Idempotent: revoking an already-revoked token returns False (the router
    maps that to 404), and the first revocation wins via the
    `revoked_at IS NULL` guard, so a double-submit can't move the timestamp.
    """
    result = await db.execute(
        update(PersonalAccessToken)
        .where(
            PersonalAccessToken.id == token_id,
            PersonalAccessToken.user_id == user_id,
            PersonalAccessToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
        .returning(PersonalAccessToken.id)
    )
    revoked = result.scalar_one_or_none() is not None
    await db.commit()
    if revoked:
        logger.info("PAT revoked: id=%s user=%s", token_id, user_id)
    return revoked


async def authenticate_token(db: AsyncSession, raw_token: str) -> PersonalAccessToken | None:
    """Resolve a raw PAT to its record, or None if it is unusable.

    None covers every failure — unknown, revoked, or expired — so the caller
    returns one constant 401 and leaks nothing about which check failed.
    Touches last_used_at as a side-effect (throttled).
    """
    result = await db.execute(
        select(PersonalAccessToken).where(
            PersonalAccessToken.token_hash == _hash_token(raw_token)
        )
    )
    token = result.scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        return None

    now = datetime.now(timezone.utc)
    if token.expires_at is not None and _as_aware(token.expires_at) <= now:
        return None

    await _touch_last_used(db, token, now)
    return token


async def _touch_last_used(
    db: AsyncSession, token: PersonalAccessToken, now: datetime
) -> None:
    """Record token usage, at most once per _LAST_USED_THROTTLE_SECONDS.

    Best-effort: a failure here must never turn a valid agent request into an
    auth error, so it is logged and swallowed.
    """
    if (
        token.last_used_at is not None
        and (now - _as_aware(token.last_used_at)).total_seconds() < _LAST_USED_THROTTLE_SECONDS
    ):
        return

    try:
        await db.execute(
            update(PersonalAccessToken)
            .where(PersonalAccessToken.id == token.id)
            .values(last_used_at=now)
        )
        await db.commit()
        token.last_used_at = now
    except Exception:  # noqa: BLE001 — usage telemetry must not break auth
        await db.rollback()
        logger.warning("PAT last_used_at update failed: id=%s", token.id, exc_info=True)
