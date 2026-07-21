"""The event catalog and the ONE payload field allowlist (webhook-001).

Everything a webhook receiver can ever learn about an entity is decided here.
Domain services offer a ``summary`` dict when they record a semantic event
(events/semantic.py); the delivery path filters that dict through
:func:`filter_summary` before the body is built and signed, so a domain cannot
widen the payload by adding a field to its own summary — the field simply never
appears on the wire until it is added to the table below.

That is the whole point of centralising it: reviewing "can a budget amount or a
personal note body reach a third party?" is a single-file read, not a repo-wide
grep. Adding a field here is the deliberate, reviewable act.

Payloads stay skinny by design (the same choice the SSE stream makes). A receiver
that needs more fetches the entity back through the REST API with its own
credentials, which keeps scope enforcement in one place.

Catalog v1 is exactly six events. ``proposal.*`` is deliberately absent until
proposal-001 lands; ``member.*`` is future work.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

#: Event name → the summary fields permitted to leave the house for that event.
#: The key set is also the catalog: an event name absent here is not deliverable.
EVENT_SUMMARY_FIELDS: dict[str, tuple[str, ...]] = {
    "todo.created": ("title", "status", "priority", "due_date"),
    "todo.completed": ("title", "status", "priority", "due_date", "completed_at"),
    "grocery.item_added": ("name", "quantity", "unit", "category", "list_id", "list_name"),
    "grocery.item_checked": ("name", "quantity", "unit", "category", "list_id", "list_name"),
    "habit.checked_in": ("habit_id", "habit_name", "scheduled_date", "completed_at"),
    "calendar.event_created": ("title", "location", "starts_at", "ends_at", "all_day"),
}

#: Human-readable blurbs for the subscription UI and the docs recipe. Kept
#: beside the allowlist so a new event cannot ship without a description.
EVENT_DESCRIPTIONS: dict[str, str] = {
    "todo.created": "A to-do was created",
    "todo.completed": "A to-do was marked done",
    "grocery.item_added": "An item was added to a grocery list",
    "grocery.item_checked": "A grocery item was checked off",
    "habit.checked_in": "A habit was checked in for a day",
    "calendar.event_created": "A calendar event was created",
}

#: Every deliverable event name, sorted — the catalog surface for validation,
#: the UI picker, and the docs.
CATALOG: tuple[str, ...] = tuple(sorted(EVENT_SUMMARY_FIELDS))


def is_known_event(event: str) -> bool:
    """True if ``event`` is in catalog v1."""
    return event in EVENT_SUMMARY_FIELDS


def _jsonable(value: Any) -> Any:
    """Coerce a summary value to something ``json.dumps`` accepts.

    Summaries come straight off ORM rows, so dates, UUIDs and Decimals are
    routine. Decimals become floats only when they are not integral (a quantity
    of ``2`` should read as ``2``, not ``2.0``); anything unrecognised is
    stringified rather than raising, because a payload must never be the reason
    a committed write appears broken.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def filter_summary(event: str, summary: dict[str, Any] | None) -> dict[str, Any]:
    """Return only the fields this event is allowed to carry, JSON-ready.

    Unknown events yield an empty summary rather than raising: an event outside
    the catalog is never dispatched in the first place, and if one somehow
    reaches here (a stored delivery row written by a newer build, say) the safe
    answer is to send nothing rather than everything. Fields present in the
    allowlist but absent from the summary are simply omitted.
    """
    allowed = EVENT_SUMMARY_FIELDS.get(event)
    if not allowed or not summary:
        return {}
    return {k: _jsonable(summary[k]) for k in allowed if k in summary}


def matches_patterns(patterns: list[str] | None, event: str) -> bool:
    """True if any subscription pattern selects ``event``.

    Supported forms: an exact name (``todo.completed``), a domain wildcard
    (``todo.*``), and the catch-all ``*``. This is the ENTIRE filter surface in
    v1, and it runs strictly AFTER the scope check — a pattern narrows what the
    subscription's owner may already see, it can never widen it.
    """
    if not patterns:
        return False
    for pattern in patterns:
        if pattern == "*" or pattern == event:
            return True
        if pattern.endswith(".*") and event.startswith(pattern[:-1]):
            return True
    return False


def validate_patterns(patterns: list[str]) -> list[str]:
    """Normalise and check subscription patterns, or raise ``ValueError``.

    Rejects a pattern that can never match anything in the catalog — a typo like
    ``todos.completed`` would otherwise create a subscription that silently
    receives nothing forever. The error names the valid values, since it is read
    by both the settings UI and any agent wiring itself up.
    """
    if not patterns:
        raise ValueError(
            "At least one event pattern is required. Valid events: "
            f"{', '.join(CATALOG)}. Wildcards: '*' or e.g. 'todo.*'."
        )
    cleaned: list[str] = []
    for raw in patterns:
        pattern = raw.strip()
        if not pattern:
            continue
        if not any(matches_patterns([pattern], event) for event in CATALOG):
            raise ValueError(
                f"Event pattern {pattern!r} matches no known event. "
                f"Valid events: {', '.join(CATALOG)}. "
                "Wildcards: '*' for everything, or a domain wildcard like 'todo.*'."
            )
        if pattern not in cleaned:
            cleaned.append(pattern)
    if not cleaned:
        raise ValueError(
            "At least one event pattern is required. Valid events: "
            f"{', '.join(CATALOG)}."
        )
    return cleaned
