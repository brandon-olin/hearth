"""
Template variable resolver.

Substitutes {{variable}} placeholders in template strings using the creating
user's locale settings (timezone, date_format, week_start).

Available variables:
  {{date}}         Full date formatted per user's date_format preference
  {{day}}          Numeric day of month (1–31, no leading zero)
  {{day_of_week}}  Full weekday name ("Thursday")
  {{week_number}}  ISO week number (01–53)
  {{month}}        Full month name ("May")
  {{month_num}}    Zero-padded month number ("05")
  {{year}}         Four-digit year ("2026")
  {{time}}         24-hour time in user's timezone ("14:30")
  {{user_name}}    User's display name, or email local part as fallback

Unknown {{variables}} are left as-is so templates don't silently corrupt.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone as _utc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from life_dashboard.auth.models import User

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")

# Supported date_format values → strftime strings
_DATE_FORMATS: dict[str, str] = {
    "MM/DD/YY": "%m/%d/%y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
}
_DEFAULT_DATE_FORMAT = "%Y-%m-%d"


def resolve_variables(
    template: str,
    user: "User",
    now: datetime | None = None,
) -> str:
    """
    Return *template* with all {{variable}} placeholders substituted.

    Args:
        template:  The string containing zero or more {{variable}} tokens.
        user:      The User whose locale settings drive formatting.
        now:       Override the current moment (useful for testing).
                   If omitted, uses datetime.now() in the user's timezone.

    Returns:
        The resolved string. Unknown variables are preserved unchanged.
    """
    # Fast exit only when there's nothing to substitute at all.
    if "{{" not in template and "%" not in template:
        return template

    # Resolve timezone — fall back to UTC if not set or unrecognisable.
    try:
        from zoneinfo import ZoneInfo
        user_tz = ZoneInfo(user.timezone) if user.timezone else _utc
    except (ImportError, KeyError):
        user_tz = _utc

    if now is None:
        now = datetime.now(tz=user_tz)
    else:
        now = now.astimezone(user_tz)

    # Build the {{date}} string from the user's preferred format.
    fmt = _DATE_FORMATS.get(user.date_format or "", _DEFAULT_DATE_FORMAT)
    date_str = now.strftime(fmt)

    substitutions: dict[str, str] = {
        "date": date_str,
        "day": str(now.day),                  # no leading zero
        "day_of_week": now.strftime("%A"),     # "Thursday"
        "week_number": now.strftime("%V"),     # ISO 8601 week, "20"
        "month": now.strftime("%B"),           # "May"
        "month_num": f"{now.month:02d}",       # "05"
        "year": str(now.year),                 # "2026"
        "time": now.strftime("%H:%M"),         # "14:30"
        "user_name": (
            user.display_name
            or (user.email.split("@")[0] if user.email else "")
        ),
    }

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        return substitutions.get(key, match.group(0))  # unknown → keep as-is

    result = _VAR_RE.sub(_replace, template)

    # Fallback: also resolve strftime-style directives (e.g. "%B %d, %Y").
    # This handles templates saved before the {{variable}} convention was
    # established, and lets users mix both styles if they want.
    if "%" in result:
        try:
            result = now.strftime(result)
        except Exception:
            pass  # malformed strftime directive — leave as-is

    return result
