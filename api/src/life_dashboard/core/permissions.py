"""
Household-level permission system.

Each household stores a ``permissions_config`` JSON blob that controls
which minimum role is required for each action on each shared domain.

Role tiers (highest to lowest):
  owner / admin  →  rank 3
  member         →  rank 2
  viewer         →  rank 1

Configurable actions per domain:
  read           — list/view items
  create         — create new items
  manage_others  — edit or delete items created by *other* users

``manage_own`` (edit/delete your own items) is always allowed for every
role — it is not configurable.

Fixed domains (not configurable):
  notes     — always personal to the individual creator
  workouts  — always personal to the individual creator
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── Role ranking ──────────────────────────────────────────────────────────────

ROLE_RANK: dict[str, int] = {
    "owner":  3,
    "admin":  3,   # treated identically to owner for permission purposes
    "member": 2,
    "viewer": 1,
    "agent":  1,   # agents have viewer-level access by default
}

# Human-readable labels used in the frontend
ROLE_LABELS: dict[str, str] = {
    "owner":  "Admins only",
    "member": "Members & above",
    "viewer": "Everyone",
}


def role_has_permission(user_role: str, required_role: str) -> bool:
    """Return True if *user_role* meets or exceeds *required_role*."""
    return ROLE_RANK.get(user_role, 0) >= ROLE_RANK.get(required_role, 1)


# ── Default permissions ───────────────────────────────────────────────────────

#: Sensible defaults applied when a household has no custom config, or
#: when a domain/action key is missing from the stored config.
DEFAULT_DOMAIN_PERMISSIONS: dict[str, dict[str, str]] = {
    "calendar": {
        "read":          "viewer",
        "create":        "viewer",
        "manage_others": "member",
    },
    "recipes": {
        "read":          "viewer",
        "create":        "viewer",
        "manage_others": "member",
    },
    "grocery": {
        "read":          "viewer",
        "create":        "viewer",
        "manage_others": "member",
    },
    "projects": {
        "read":          "viewer",
        "create":        "viewer",
        "manage_others": "member",
    },
    "todos": {
        "read":          "viewer",
        "create":        "viewer",
        # Kids can't delete others' todos (e.g. chores assigned by parents)
        "manage_others": "member",
    },
    "documents": {
        "read":          "viewer",
        "create":        "viewer",
        "manage_others": "member",
    },
    "goals": {
        "read":          "viewer",
        "create":        "viewer",
        "manage_others": "member",
    },
}

#: Domains whose permissions are fixed and cannot be configured.
FIXED_PERSONAL_DOMAINS = {"notes", "workouts"}

#: All configurable domains in display order for the settings UI.
CONFIGURABLE_DOMAINS: list[dict[str, str]] = [
    {"key": "calendar",  "label": "Calendar",       "description": "Events and appointments"},
    {"key": "recipes",   "label": "Recipes",         "description": "Recipe library"},
    {"key": "grocery",   "label": "Grocery lists",   "description": "Shopping lists"},
    {"key": "projects",  "label": "Projects & todos","description": "Projects and task lists"},
    {"key": "todos",     "label": "To-dos",          "description": "Individual tasks"},
    {"key": "documents", "label": "Documents",       "description": "Shared documents"},
    {"key": "goals",     "label": "Goals",           "description": "Household goals"},
]


# ── Config helpers ────────────────────────────────────────────────────────────

def merge_with_defaults(config: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """
    Return a fully-populated permissions config, filling any missing
    domains or actions with their defaults.
    """
    result: dict[str, dict[str, str]] = {}
    for domain, defaults in DEFAULT_DOMAIN_PERMISSIONS.items():
        stored = (config or {}).get(domain, {})
        result[domain] = {
            action: stored.get(action, default_role)
            for action, default_role in defaults.items()
        }
    return result


def validate_permissions_config(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """
    Validate and normalise a permissions config supplied by the client.
    Raises ValueError if any role value is unrecognised.
    Returns a clean, fully-populated config.
    """
    valid_roles = set(ROLE_RANK.keys())
    valid_actions = {"read", "create", "manage_others"}

    for domain, actions in config.items():
        if domain not in DEFAULT_DOMAIN_PERMISSIONS:
            raise ValueError(f"Unknown domain: {domain!r}")
        if not isinstance(actions, dict):
            raise ValueError(f"Actions for domain {domain!r} must be an object")
        for action, role in actions.items():
            if action not in valid_actions:
                raise ValueError(f"Unknown action {action!r} for domain {domain!r}")
            if role not in valid_roles:
                raise ValueError(
                    f"Invalid role {role!r} for {domain}.{action}. "
                    f"Must be one of: {sorted(valid_roles)}"
                )

    return merge_with_defaults(config)


# ── DB helpers ────────────────────────────────────────────────────────────────

async def get_item_creator(
    db: AsyncSession,
    model_class: type,
    item_id: uuid.UUID,
    household_id: uuid.UUID,
) -> uuid.UUID | None:
    """
    Return the ``created_by_user_id`` of an item, or None if the item doesn't exist.
    Used to determine whether a write is to the user's own item (always allowed)
    or to another user's item (requires manage_others permission).
    """
    from sqlalchemy import select as _select  # local import to avoid top-level cycle

    result = await db.execute(
        _select(model_class.created_by_user_id).where(  # type: ignore[attr-defined]
            model_class.id == item_id,  # type: ignore[attr-defined]
            model_class.household_id == household_id,  # type: ignore[attr-defined]
        )
    )
    return result.scalar_one_or_none()


async def load_household_permissions(
    db: AsyncSession,
    household_id: uuid.UUID,
) -> dict[str, dict[str, str]]:
    """
    Load the household's custom permissions config from the DB and merge
    with defaults.  Returns a fully-populated config dict.
    """
    from life_dashboard.auth.models import Household  # avoid circular import

    result = await db.execute(
        select(Household.permissions_config).where(Household.id == household_id)
    )
    raw = result.scalar_one_or_none()
    return merge_with_defaults(raw)


def check_permission(
    permissions: dict[str, dict[str, str]],
    domain: str,
    action: str,
    user_role: str,
) -> bool:
    """
    Return True if *user_role* is allowed to perform *action* on *domain*.

    :param permissions: Fully-populated permissions dict from merge_with_defaults().
    :param domain:      Domain key, e.g. "todos", "calendar".
    :param action:      Action key: "read", "create", or "manage_others".
    :param user_role:   The user's membership role string.
    """
    domain_config = permissions.get(domain, DEFAULT_DOMAIN_PERMISSIONS.get(domain, {}))
    required_role = domain_config.get(action, "viewer")
    return role_has_permission(user_role, required_role)
