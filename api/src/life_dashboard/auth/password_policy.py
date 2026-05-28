"""Password policy for Hearth.

Rules (applied consistently at every password-setting endpoint):
  - At least 8 characters
  - At most 50 characters  (generous upper limit; 1Password-style long passwords welcome)
  - At least one digit (0–9)
  - At least one special character (!@#$%^&* etc.)

Returns None when valid, a human-readable error string when invalid.
Intentionally not raising exceptions here so callers can decide how to surface the error.
"""

import re

MIN_LENGTH = 8
MAX_LENGTH = 50

_HAS_DIGIT   = re.compile(r"\d")
_HAS_SPECIAL = re.compile(r"[^A-Za-z0-9]")


def validate_password(password: str) -> str | None:
    """Return an error message if the password fails policy, or None if it's acceptable."""
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Password must be {MAX_LENGTH} characters or fewer."
    if not _HAS_DIGIT.search(password):
        return "Password must contain at least one number."
    if not _HAS_SPECIAL.search(password):
        return "Password must contain at least one special character."
    return None
