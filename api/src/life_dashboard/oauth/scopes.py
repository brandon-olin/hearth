"""OAuth scope strings ⇄ PAT scope blobs.

An OAuth `scope` parameter is a space-delimited string; the PAT primitive
(security-006) speaks a `{"<domain>": "read" | "write"}` JSONB blob. This module
is the single translation point between the two so the OAuth layer never invents
its own permission vocabulary — every scope it can grant is a PAT scope, and
`validate_scopes` (auth/pat_scopes.py) stays the one authority on what is valid.

Wire format: each space-separated token is ``<domain>:<level>``, e.g.::

    todos:write calendar:read grocery:write

`<domain>` is a key of PAT_SCOPE_DOMAINS; `<level>` is "read", "propose", or
"write". A bare domain with no level is rejected rather than guessed — an agent
asking for "todos" must say whether it wants to write.
"""
from __future__ import annotations

from life_dashboard.auth.pat_scopes import (
    PAT_ACCESS_LEVELS,
    PAT_SCOPE_DOMAINS,
    tier_rank,
    validate_scopes,
)

#: Every scope string this server advertises as supported (RFC 8414 metadata).
#: Sorted for a stable, greppable metadata document.
SUPPORTED_SCOPE_STRINGS: tuple[str, ...] = tuple(
    f"{domain}:{level}"
    for domain in sorted(PAT_SCOPE_DOMAINS)
    for level in PAT_ACCESS_LEVELS
)


class OAuthScopeError(ValueError):
    """A requested OAuth scope string was malformed or named an unknown grant.

    The message is safe to surface to the client — it names the bad token and
    the valid vocabulary, mirroring how validate_scopes reports PAT errors."""


def parse_scope(scope: str | None) -> dict[str, str]:
    """Parse an OAuth `scope` string into a validated PAT scopes blob.

    Empty or whitespace-only input raises — an OAuth grant with no scope would
    mint a PAT that authenticates but authorizes nothing, the same footgun
    validate_scopes rejects for direct PAT creation. Duplicate domains take the
    higher access level ("write" > "read") so ``todos:read todos:write`` grants
    write rather than the last-wins accident.
    """
    if scope is None or not scope.strip():
        raise OAuthScopeError("The `scope` parameter is required and must be non-empty.")

    requested: dict[str, str] = {}
    for token in scope.split():
        domain, sep, level = token.partition(":")
        if not sep:
            raise OAuthScopeError(
                f"Malformed scope {token!r}. Each scope must be `<domain>:<level>`, "
                f"e.g. 'todos:write'."
            )
        # The strongest requested tier wins for a repeated domain (read <
        # propose < write), rather than last-one-wins. An unrecognised level
        # ranks below everything but is still stored on first sight, so
        # validate_scopes below can name it in the error.
        if domain in requested and tier_rank(requested[domain]) >= tier_rank(level):
            continue
        requested[domain] = level

    try:
        # validate_scopes is the single authority on the vocabulary and raises
        # ValueError naming the valid domains / levels — reuse it verbatim.
        return validate_scopes(requested)
    except ValueError as exc:
        raise OAuthScopeError(str(exc)) from exc


def to_scope_string(pat_scopes: dict[str, str]) -> str:
    """Render a PAT scopes blob back to an OAuth `scope` string.

    Used in the token response's `scope` field so the client learns exactly what
    was granted (which may differ from what it asked for if a future consent
    step narrows it). Deterministically ordered for stable responses and tests.
    """
    return " ".join(f"{domain}:{level}" for domain, level in sorted(pat_scopes.items()))
