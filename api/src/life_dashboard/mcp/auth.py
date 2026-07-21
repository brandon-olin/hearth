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
from life_dashboard.auth.pat_rate_limit import check_rate_limit
from life_dashboard.auth.pat_scopes import (
    SCOPE_TO_PERMISSION_DOMAIN,
    check_scope,
    is_pat,
    min_tier,
    scope_tier,
    tier_rank,
)
from life_dashboard.auth.pat_service import authenticate_token
from life_dashboard.auth.service import get_user_by_id
from life_dashboard.core.permissions import (
    check_permission,
    load_household_permissions,
    resolve_permission_tier,
)
from life_dashboard.core.settings import settings


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
    pat_id: uuid.UUID | None
    #: Set only when this identity is being replayed by an approved proposal
    #: (proposal-001), so the audit row it produces carries the link back to the
    #: request a human said yes to. None on every live tool call.
    via_proposal_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AuthDecision:
    """The outcome of authorizing one tool call, tier included.

    ``authorize`` cannot answer with a bare identity any more. With the
    ``propose`` tier in play (proposal-001) a write has three outcomes, not two:
    execute, capture as a proposal, or refuse. Refusal still raises; the other
    two are distinguished by :attr:`tier`, so the tool decides what to do rather
    than inferring it from the absence of an exception.

    Delegating properties keep every read tool's ``ident.household_id`` working
    unchanged — only write tools ever look at the tier.
    """

    identity: PatIdentity
    #: Effective tier for the requested action: min(token scope, member ceiling)
    #: under read < propose < write.
    tier: str
    #: The action the caller asked for ("read" or "write").
    requested: str

    @property
    def proposed(self) -> bool:
        """True when this write must be captured instead of performed."""
        return self.requested != "read" and self.tier == "propose"

    @property
    def user_id(self) -> uuid.UUID:
        return self.identity.user_id

    @property
    def household_id(self) -> uuid.UUID:
        return self.identity.household_id

    @property
    def household_name(self) -> str | None:
        return self.identity.household_name

    @property
    def role(self) -> str:
        return self.identity.role

    @property
    def pat_id(self) -> uuid.UUID | None:
        return self.identity.pat_id

    @property
    def via_proposal_id(self) -> uuid.UUID | None:
        return self.identity.via_proposal_id


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

    # security-007: cloud-tier per-token throttle. Mirrors the REST path so an
    # OAuth-minted token hitting MCP is bounded identically. No-op off cloud.
    if settings.deployment_tier == "cloud" and not check_rate_limit(
        pat.id, settings.pat_rate_limit_per_minute
    ):
        raise MCPAuthError("Rate limit exceeded for this token. Slow down and retry shortly.")

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


def _permission_action(action: str) -> str:
    """Map an MCP tool action to the household-permission action it needs.

    "write" maps to "create" — the coarsest write permission the household
    config models (per-item ``manage_others`` stays the service's job). Mirrors
    the same mapping in auth/dependencies._enforce_pat_scope so an MCP write and
    the equivalent REST write are gated identically."""
    return "read" if action == "read" else "create"


async def _within_member_ceiling(
    db: AsyncSession, identity: PatIdentity, scope_domain: str, action: str = "read"
) -> bool:
    """Layer 2 — is *action* on ``scope_domain`` within the owning member's own
    ceiling? Only domains with a configurable household permission are checked;
    others are governed by the token scope alone (mirrors SCOPE_TO_PERMISSION_
    DOMAIN usage in the REST dependency)."""
    permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(scope_domain)
    if permission_domain is None:
        return True
    permissions = await load_household_permissions(db, identity.household_id)
    return check_permission(
        permissions, permission_domain, _permission_action(action), identity.role
    )


async def _member_ceiling_tier(
    db: AsyncSession, identity: PatIdentity, scope_domain: str, action: str
) -> str:
    """Layer 2 as a tier rather than a boolean — the ceiling's own read/propose/
    write answer for *action* on ``scope_domain``.

    A domain with no configurable household permission has no ceiling to resolve
    here (its routers' role gates are the ceiling), so it caps at ``write`` and
    the token scope alone decides. Same rule as :func:`_within_member_ceiling`,
    which stays the boolean form the read paths use.
    """
    permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(scope_domain)
    if permission_domain is None:
        return "write"
    permissions = await load_household_permissions(db, identity.household_id)
    return resolve_permission_tier(
        permissions, permission_domain, _permission_action(action), identity.role
    )


async def can_read(
    db: AsyncSession, pat: PersonalAccessToken, identity: PatIdentity, scope_domain: str
) -> bool:
    """True if this token may read ``scope_domain`` — token scope ∩ member
    ceiling — without raising. Used by get_household_summary to include a
    domain's count only when the token is actually entitled to that domain,
    so a single-scope token can never learn cross-domain data."""
    if not check_scope(pat.scopes or {}, scope_domain, "read"):
        return False
    return await _within_member_ceiling(db, identity, scope_domain, "read")


async def authorize(
    db: AsyncSession, ctx, scope_domain: str, action: str = "read"
) -> AuthDecision:
    """Authorize *action* ("read" or "write") on ``scope_domain`` for the PAT
    behind this tool call, and return the tier it resolved to.

    Enforces the same two layers as the REST PAT path (auth/dependencies.py):

      1. **Token scope** — the tier this token was granted on this domain.
      2. **Member ceiling** — the tier the owning member may reach in the app.
         This is what makes a household-agent (viewer-rank) token safe: it can
         create in domains where ``create`` defaults to viewer (grocery, todos)
         but is refused wherever an admin has raised the bar to member+.

    **Effective permission is min(token, ceiling)** under read < propose < write.
    A write asked for by a token or member that only reaches ``propose`` is not a
    failure and not a success — it returns a decision whose ``proposed`` is True,
    and the tool records a Proposal instead of executing. Raising there would be
    wrong: ``propose`` exists precisely so that call has a third outcome.

    Read-only access to a write is still a hard failure. A ``read``-scoped token
    calling a write tool raises, and must never quietly become a proposal — the
    household granted it no right to ask.

    Raises :class:`MCPAuthError` on refusal, with a message distinguishing the
    two layers. The returned decision carries the caller identity that feeds
    household + visibility scoping in the domain services.
    """
    pat, identity = await resolve_pat(db, ctx)

    token = scope_tier(pat.scopes or {}, scope_domain)
    ceiling = await _member_ceiling_tier(db, identity, scope_domain, action)
    effective = min_tier(token, ceiling)

    # A write may proceed at "write" (execute) or "propose" (capture); anything
    # lower is a refusal. A read needs "read" or better.
    floor = "read" if action == "read" else "propose"
    if tier_rank(effective) < tier_rank(floor):
        # Name the layer that actually bound, so the agent learns something
        # actionable rather than a generic denial. Wording unchanged from before
        # the propose tier — it is the message agents already handle.
        if tier_rank(token) <= tier_rank(ceiling):
            raise MCPAuthError(f"Token does not have {action} access to {scope_domain}.")
        permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(scope_domain)
        raise MCPAuthError(
            f"Your account does not have {_permission_action(action)} permission "
            f"for {permission_domain}. A token cannot exceed its owner's access."
        )

    return AuthDecision(identity=identity, tier=effective, requested=action)
