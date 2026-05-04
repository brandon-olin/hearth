from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()

# Sentinel written by the Phase 0 migration for the bootstrap user.
# argon2 hashes always start with '$argon2', so '!' can never be a real hash.
SENTINEL_HASH = "!"


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Returns True if plain matches hashed. Always False for the sentinel."""
    if hashed == SENTINEL_HASH:
        return False
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def is_sentinel(hashed: str) -> bool:
    """True when the user's password has never been set (bootstrap state)."""
    return hashed == SENTINEL_HASH


def needs_rehash(hashed: str) -> bool:
    """True if argon2 parameters have drifted and the hash should be upgraded on next login."""
    if hashed == SENTINEL_HASH:
        return False
    return _ph.check_needs_rehash(hashed)
