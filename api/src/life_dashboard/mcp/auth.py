"""
PAT authorization for MCP tools (mcp-001 / plans/open-hearth/mcp-server.md).

The MCP endpoint is mounted in-process at ``/mcp`` and authenticated with the
same Personal Access Tokens as the REST API (security-006). Every tool call
carries the PAT as an ``Authorization: Bearer hearth_pat_...`` header; the tool
resolves it to a member + household here before touching any data.

Why authorize per tool-call rather than in ASGI middleware:

* The scope a call needs is domain-specific (``todos`` read vs ``calendar``
  read), and only the tool knows its own domain. Doing it here keeps the
  scope decision next to the data access, mirroring how each REST route
  declares its own dependency.
* A single ``AsyncSession`` covers both the auth lookup and the data query, so
  there is no second connection per call.

The returned :class:`PatIdentity` carries the owning member's ``user_id`` — every
tool passes it straight into ``apply_visibility_filter`` so an agent sees shared
data plus that member's personal data, and never another member's personal or
any sensitive scope. This is the agent permission model from the track doc.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import Household, HouseholdMembership, PersonalAccessToken
from life_dashboard.auth.pat_scopes import (
    SCOPE_TO_PERMISSION_DOMAIN,
    check_scope,
    is_pat,
)
from life_dashboard.auth.pat_service import authenticate_token
from life_dashboard.auth.service import get_user_by_id
from life_dashboard.core.permissions import check_permission, load_household_permissions


class MCPAuthError(Exception):
    """A tool call could not be authorized — missing, invalid, or under-scoped
    credential. FastMCP surfaces the message to the calling agent as a tool
    error; the text is deliberately non-specific about which check failed."""


@dataclass(frozen=True)
class PatIdentity:
    """The resolved caller behind a PAT-authenticated MCP tool call."""

    user_id: uuid.UUID
    household_id: uuid.UUID
    household_name: str | None
    role: str
    pat_id: uuid.UUID


def _bearer_token(ctx) -> str:
    """Pull the raw Bearer credential off the live HTTP request.

    FastMCP attaches the Starlette request to the request context for the
    streamable-HTTP transport; ``request`` is None only for transports that
    have no HTTP request (e.g. stdio), which this server never uses.
    """
    request = getattr(ctx.request_context, "request", None)
    header = request.headers.get("authorization", "") if request is not None else ""
    if not header.startswith("Bearer "):
        raise MCPAuthError(
            "Not authenticated. Provide a Hearth personal access token as a "
            "Bearer token in the Authorization header."
        )
    return header.removeprefix("Bearer ").strip()


async def resolve_pat(db: AsyncSession, ctx) -> tuple[PersonalAccessToken, PatIdentity]:
    """Authenticate the PAT behind this call and resolve its owner + household.

    Does NOT check any domain scope — that is :func:`can_read` / :func:`authorize`.
    Raises :class:`MCPAuthError` if the credential is missing, malformed,
    invalid/expired, or its owner is inactive or has no membership.
    """
    raw = _bearer_token(ctx)
    if not is_pat(raw):
        raise MCPAuthError("Credential is not a Hearth personal access token.")

    pat = await authenticate_token(db, raw)
    if pat is None:
        raise MCPAuthError("Invalid or expired token.")

    user = await get_user_by_id(db, pat.user_id)
    if user is None or not user.is_active:
        raise MCPAuthError("Token owner is inactive.")

    membership = (
        await db.execute(
            select(HouseholdMembership).where(HouseholdMembership.user_id == pat.user_id)
        )
    ).scalar_one_or_none()
    if membership is None:
        raise MCPAuthError("Token owner has no household membership.")

    household = (
        await db.execute(
            select(Household).where(Household.id == membership.household_id)
        )
    ).scalar_one_or_none()

    identity = PatIdentity(
        user_id=pat.user_id,
        household_id=membership.household_id,
        household_name=household.name if household else None,
        role=membership.role.value,
        pat_id=pat.id,
    )
    return pat, identity


async def _within_member_ceiling(
    db: AsyncSession, identity: PatIdentity, scope_domain: str
) -> bool:
    """Layer 2 — is a read on ``scope_domain`` within the owning member's own
    ceiling? Only domains with a configurable household permission are checked;
    others are governed by the token scope alone (mirrors SCOPE_TO_PERMISSION_
    DOMAIN usage in the REST dependency)."""
    permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(scope_domain)
    if permission_domain is None:
        return True
    permissions = await load_household_permissions(db, identity.household_id)
    return check_permission(permissions, permission_domain, "read", identity.role)


async def can_read(
    db: AsyncSession, pat: PersonalAccessToken, identity: PatIdentity, scope_domain: str
) -> bool:
    """True if this token may read ``scope_domain`` — token scope ∩ member
    ceiling — without raising. Used by get_household_summary to include a
    domain's count only when the token is actually entitled to that domain,
    so a single-scope token can never learn cross-domain data."""
    if not check_scope(pat.scopes or {}, scope_domain, "read"):
        return False
    return await _within_member_ceiling(db, identity, scope_domain)


async def authorize(db: AsyncSession, ctx, scope_domain: str) -> PatIdentity:
    """Authorize a read on ``scope_domain`` for the PAT behind this tool call.

    Enforces the same two layers as the REST PAT path (auth/dependencies.py):

      1. **Token scope** — the token was granted read on this domain.
      2. **Member ceiling** — the owning member may read this domain in the app.

    Raises :class:`MCPAuthError` on any failure, with a message distinguishing
    the two layers. Returns the caller identity to feed the household +
    visibility scoping in the domain services.
    """
    pat, identity = await resolve_pat(db, ctx)

    # Layer 1 — token scope. Read is the only action v1 exposes.
    if not check_scope(pat.scopes or {}, scope_domain, "read"):
        raise MCPAuthError(f"Token does not have read access to {scope_domain}.")

    # Layer 2 — member ceiling.
    if not await _within_member_ceiling(db, identity, scope_domain):
        permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(scope_domain)
        raise MCPAuthError(
            f"Your account does not have read permission for {permission_domain}. "
            "A token cannot exceed its owner's access."
        )

    return identity
