from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt  # noqa: F401 — JWTError re-exported for callers

from life_dashboard.core.settings import settings


def create_access_token(subject: str) -> str:
    """Creates a signed JWT. subject is the user UUID (str)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decodes and validates a JWT. Raises jose.JWTError if invalid or expired.

    Callers should catch JWTError and raise HTTP 401.
    """
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
