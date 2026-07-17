"""
Scope vocabulary and request-authorization rules for Personal Access Tokens.

security-006 / plans/open-hearth/mcp-server.md.

A PAT carries a scopes JSONB blob of the shape::

    {"todos": "write", "calendar": "read"}

Domain keys come from PAT_SCOPE_DOMAINS; values are "read" or "write"
("write" implies read). A domain absent from the blob is not granted at all.

Authorization for a request is decided in two independent layers, and both
must pass (see resolve_required_scope + check_scope, and the member-ceiling
check in dependencies.get_current_user):

  Layer 1 — member ceiling: what the token's owning member may do in the app.
  Layer 2 — token scope: what this specific token was granted.

Effective permission is the intersection. A token can never exceed its owner.

Path mapping is deny-by-default: a request path that maps to no scope domain
is refused for PAT-authenticated callers. This is deliberate and load-bearing —
it means /auth (a PAT cannot mint more PATs or change the password), /ai,
/setup and /uploads are unreachable with a PAT without anyone having to
remember to block them. New routers are locked out until explicitly mapped.
"""
from __future__ import annotations

# ── Scope vocabulary ──────────────────────────────────────────────────────────

#: Scope domain → the router path prefixes it authorizes.
#: Adding a router here is the *only* way to expose it to PATs.
PAT_SCOPE_DOMAINS: dict[str, tuple[str, ...]] = {
    "todos":         ("/todos",),
    "projects":      ("/projects",),
    "calendar":      ("/events",),
    "grocery":       ("/grocery-lists",),
    "recipes":       ("/recipes",),
    "documents":     ("/documents",),
    "goals":         ("/goals",),
    "habits":        ("/habits",),
    "notes":         ("/notes",),
    "workouts":      ("/workouts",),
    "contacts":      ("/contacts",),
    "budget":        ("/budget",),
    "tags":          ("/tags",),
    "notifications": ("/notifications",),
    "collections":   ("/collections", "/templates"),
    "household":     ("/households",),
}

#: Human-readable labels for the token-creation UI.
PAT_SCOPE_LABELS: dict[str, str] = {
    "todos":         "To-dos",
    "projects":      "Projects",
    "calendar":      "Calendar",
    "grocery":       "Grocery lists",
    "recipes":       "Recipes",
    "documents":     "Documents",
    "goals":         "Goals",
    "habits":        "Habits",
    "notes":         "Notes",
    "workouts":      "Workouts",
    "contacts":      "Contacts",
    "budget":        "Budget",
    "tags":          "Tags",
    "notifications": "Notifications",
    "collections":   "Collections & templates",
    "household":     "Household & members",
}

#: Scope domain → key in core.permissions.DEFAULT_DOMAIN_PERMISSIONS.
#: Only these domains have a configurable household permission to enforce the
#: member ceiling against. Domains absent here are still ceiling-checked by the
#: routers' own role gates — this map only drives the extra check in the PAT path.
SCOPE_TO_PERMISSION_DOMAIN: dict[str, str] = {
    "todos":     "todos",
    "projects":  "projects",
    "calendar":  "calendar",
    "grocery":   "grocery",
    "recipes":   "recipes",
    "documents": "documents",
    "goals":     "goals",
}

PAT_ACCESS_LEVELS: tuple[str, ...] = ("read", "write")

#: HTTP methods that only read. Everything else counts as a write.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


# ── Token format ──────────────────────────────────────────────────────────────

#: Recognisable prefix so tokens are greppable in logs and catchable by
#: secret scanners (convention copied from Home Assistant / Gitea / GitHub).
PAT_TOKEN_PREFIX = "hearth_pat_"


def is_pat(raw_token: str) -> bool:
    """True if a Bearer credential is a PAT rather than a session JWT."""
    return raw_token.startswith(PAT_TOKEN_PREFIX)


# ── Pure authorization helpers ────────────────────────────────────────────────

def validate_scopes(scopes: dict) -> dict[str, str]:
    """Validate a client-supplied scopes blob and return it normalised.

    Raises ValueError on an unknown domain, a bad access level, or an empty
    grant. A token with no scopes would authenticate but authorize nothing,
    which is a footgun rather than a useful state.
    """
    if not isinstance(scopes, dict) or not scopes:
        raise ValueError("scopes must be a non-empty object of domain -> read|write")

    normalised: dict[str, str] = {}
    for domain, level in scopes.items():
        if domain not in PAT_SCOPE_DOMAINS:
            raise ValueError(
                f"Unknown scope domain: {domain!r}. "
                f"Must be one of: {', '.join(sorted(PAT_SCOPE_DOMAINS))}"
            )
        if level not in PAT_ACCESS_LEVELS:
            raise ValueError(
                f"Invalid access level {level!r} for scope {domain!r}. "
                f"Must be one of: {', '.join(PAT_ACCESS_LEVELS)}"
            )
        normalised[domain] = level
    return normalised


def action_for_method(method: str) -> str:
    """Map an HTTP method to the access level it requires."""
    return "read" if method.upper() in _READ_METHODS else "write"


def resolve_required_scope(path: str, method: str) -> tuple[str, str] | None:
    """Return (scope_domain, action) required for a request, or None if the
    path is not exposed to PATs at all.

    None means deny — see the module docstring on deny-by-default.
    """
    # Longest prefix wins so a future "/todos-archive" router can't be
    # authorized by the "/todos" scope through a naive startswith match.
    best: tuple[str, int] | None = None
    for domain, prefixes in PAT_SCOPE_DOMAINS.items():
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                if best is None or len(prefix) > best[1]:
                    best = (domain, len(prefix))
    if best is None:
        return None
    return best[0], action_for_method(method)


def check_scope(scopes: dict[str, str], domain: str, action: str) -> bool:
    """True if the token's scopes grant *action* on *domain*.

    Read defensively — scopes is JSONB and may predate a vocabulary change.
    """
    granted = (scopes or {}).get(domain)
    if granted == "write":
        return True  # write implies read
    return granted == "read" and action == "read"
