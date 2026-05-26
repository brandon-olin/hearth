"""
Field-level encryption for sensitive database columns.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) from the
`cryptography` package — already a transitive dependency via python-jose.

Key configuration
-----------------
Set ``FIELD_ENCRYPTION_KEY`` in the environment (or .env) to a Fernet key.
Generate one with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Key rotation
------------
``FIELD_ENCRYPTION_KEY`` may be a comma-separated list of keys.  The first key
is used for all new writes; all keys are tried when decrypting.  To rotate:

1. Prepend the new key to the comma-separated list.
2. Re-encrypt stored values in a background job (or next migration).
3. Once done, remove the old key from the list.

Local dev
---------
If ``FIELD_ENCRYPTION_KEY`` is not set, values pass through unencrypted.
A one-time warning is logged so the gap is visible without being fatal.
Set the key in production — every deploy target that stores real user data.
"""

import json
import logging
import os
from typing import Any

from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

# Module-level flag so we only log the "no key" warning once.
_warned_no_key: bool = False


def _get_fernet() -> MultiFernet | None:
    """Return a MultiFernet instance from FIELD_ENCRYPTION_KEY, or None if unset."""
    global _warned_no_key
    raw = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
    if not raw:
        if not _warned_no_key:
            logger.warning(
                "FIELD_ENCRYPTION_KEY is not set — encrypted columns will store "
                "plaintext. Set this variable before deploying to production."
            )
            _warned_no_key = True
        return None
    # Support comma-separated list for zero-downtime key rotation.
    keys = [k.strip().encode() for k in raw.split(",") if k.strip()]
    return MultiFernet([Fernet(k) for k in keys])


class EncryptedText(TypeDecorator):
    """SQLAlchemy column type that transparently encrypts/decrypts Text values.

    The underlying DB column stays ``TEXT``; no schema change is required when
    adding encryption to an existing text field (only a data migration to
    encrypt existing plaintext rows).

    Graceful degradation
    --------------------
    * If the key is not configured: values pass through as-is (local dev).
    * If a stored value cannot be decrypted (e.g. a plaintext row from before
      the data migration ran): the raw value is returned with a warning.
      This prevents the app from crashing mid-migration.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        """Encrypt on write."""
        if value is None:
            return None
        fernet = _get_fernet()
        if fernet is None:
            return value
        return fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        """Decrypt on read."""
        if value is None:
            return None
        fernet = _get_fernet()
        if fernet is None:
            return value
        try:
            return fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            # Row predates encryption — return as-is so migration can proceed.
            logger.warning(
                "EncryptedText: could not decrypt a value — returning raw "
                "(data migration may still be pending)"
            )
            return value


class EncryptedJSON(TypeDecorator):
    """SQLAlchemy column type that JSON-serialises a value then encrypts it.

    The underlying DB column must be ``TEXT`` (not ``JSON``) because the
    encrypted ciphertext is not valid JSON.  Use an Alembic migration to
    change any existing ``JSON`` columns to ``TEXT`` before deploying.

    Graceful degradation
    --------------------
    Same pattern as :class:`EncryptedText` — plaintext JSON values are
    transparently handled during rollout.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> str | None:
        """Serialise to JSON then encrypt."""
        if value is None:
            return None
        serialized = json.dumps(value)
        fernet = _get_fernet()
        if fernet is None:
            return serialized
        return fernet.encrypt(serialized.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> Any:
        """Decrypt then deserialise from JSON."""
        if value is None:
            return None
        fernet = _get_fernet()
        if fernet is None:
            # No encryption — value should be plain JSON.
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        try:
            decrypted = fernet.decrypt(value.encode()).decode()
            return json.loads(decrypted)
        except InvalidToken:
            # Row predates encryption — attempt raw JSON parse.
            logger.warning(
                "EncryptedJSON: could not decrypt a value — attempting raw "
                "JSON parse (data migration may still be pending)"
            )
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
