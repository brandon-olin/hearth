"""PAT authorization for Alexa intents (voice-002).

The account-linking token Alexa hands back is a Hearth Personal Access Token —
minted directly (self-hosted paste) or by the OAuth grant (security-007, cloud
account linking). It authorizes exactly as it does on the REST and MCP paths:

  1. **Token scope** — the token was granted this action on this domain.
  2. **Member ceiling** — the owning member may do this in the app. A token can
     never exceed its owner (a viewer-rank household-agent token can't create
     where an admin raised the bar to member+).

This is the same two-layer model as :mod:`life_dashboard.mcp.auth`; the sibling
there reads the credential off an HTTP Bearer header, whereas Alexa carries it
in the request JSON, so this module resolves from a raw token string instead.
The resolved :class:`~life_dashboard.mcp.auth.PatIdentity` is reused unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import Household, HouseholdMembership, PersonalAccessToken
from life_dashboard.auth.pat_rate_limit import check_rate_limit
from life_dashboard.auth.pat_scopes import (
    SCOPE_TO_PERMISSION_DOMAIN,
    is_pat,
    min_tier,
    scope_tier,
    tier_rank,
)
from life_dashboard.auth.pat_service import authenticate_token
from life_dashboard.auth.service import get_user_by_id
from life_dashboard.core.permissions import (
    load_household_permissions,
    resolve_permission_tier,
)
from life_dashboard.core.settings import settings
from life_dashboard.mcp.auth import PatIdentity

#: Distinguishes an auth failure the user can fix by (re)linking their account
#: from one they cannot. The router maps each to a different spoken response.
UNAUTHENTICATED = "unauthenticated"  # no token, or not a Hearth PAT at all
INVALID_TOKEN = "invalid_token"      # token present but unknown/expired/revoked
DENIED = "denied"                    # valid token, but scope or ceiling refuses


class VoiceAuthError(Exception):
    """An Alexa intent could not be authorized. ``reason`` is one of the module
    constants above so the router can choose "link your account" vs. "you don't
    have permission" wording."""

    def __init__(self, message: str, *, reason: str = DENIED):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class VoiceDecision:
    """The outcome of authorizing one intent, tier included.

    The voice equivalent of :class:`~life_dashboard.mcp.auth.AuthDecision`, and
    it exists for the same reason: with the ``propose`` tier in play a write has
    three outcomes, not two. A speaker whose household requires approval should
    hear "I'll ask" — not "you don't have permission", which is both wrong and
    the kind of thing a kid learns to stop asking after.
    """

    pat: PersonalAccessToken
    identity: PatIdentity
    #: Effective tier for the requested action: min(token scope, member ceiling).
    tier: str
    #: The action the intent asked for ("read" or "write").
    requested: str

    @property
    def proposed(self) -> bool:
        """True when this write must be captured for a human instead of done."""
        return self.requested != "read" and self.tier == "propose"


def _permission_action(action: str) -> str:
    """Map an intent action to the household-permission action it needs — "write"
    is gated by the coarse "create" permission, mirroring mcp.auth."""
    return "read" if action == "read" else "create"


async def resolve_identity(
    db: AsyncSession, raw_token: str | None
) -> tuple[PersonalAccessToken, PatIdentity]:
    """Authenticate the account-linking token and resolve its owner + household.

    Does not check any domain scope — that is :func:`authorize`. Raises
    :class:`VoiceAuthError` with a ``reason`` the router turns into speech.
    """
    if not raw_token:
        raise VoiceAuthError("No account-linking token.", reason=UNAUTHENTICATED)
    if not is_pat(raw_token):
        raise VoiceAuthError("Not a Hearth token.", reason=UNAUTHENTICATED)

    pat = await authenticate_token(db, raw_token)
    if pat is None:
        raise VoiceAuthError("Invalid or expired token.", reason=INVALID_TOKEN)

    # security-007: cloud-tier per-token throttle, identical to the REST and MCP
    # paths so an internet-facing account-linked token is bounded the same way.
    # No-op off the cloud tier.
    if settings.deployment_tier == "cloud" and not check_rate_limit(
        pat.id, settings.pat_rate_limit_per_minute
    ):
        raise VoiceAuthError("Rate limit exceeded.", reason=DENIED)

    user = await get_user_by_id(db, pat.user_id)
    if user is None or not user.is_active:
        raise VoiceAuthError("Token owner is inactive.", reason=INVALID_TOKEN)

    membership = (
        await db.execute(
            select(HouseholdMembership).where(HouseholdMembership.user_id == pat.user_id)
        )
    ).scalar_one_or_none()
    if membership is None:
        raise VoiceAuthError("Token owner has no household.", reason=INVALID_TOKEN)

    household = (
        await db.execute(select(Household).where(Household.id == membership.household_id))
    ).scalar_one_or_none()

    identity = PatIdentity(
        user_id=pat.user_id,
        household_id=membership.household_id,
        household_name=household.name if household else None,
        role=membership.role.value,
        pat_id=pat.id,
    )
    return pat, identity


async def _member_ceiling_tier(
    db: AsyncSession, identity: PatIdentity, scope_domain: str, action: str
) -> str:
    """Layer 2 as a tier rather than a boolean — the ceiling's own read/propose/
    write answer. A domain with no configurable household permission has no
    ceiling to resolve here (its routers' role gates are the ceiling), so it caps
    at ``write``. Mirrors ``mcp.auth._member_ceiling_tier`` exactly."""
    permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(scope_domain)
    if permission_domain is None:
        return "write"
    permissions = await load_household_permissions(db, identity.household_id)
    return resolve_permission_tier(
        permissions, permission_domain, _permission_action(action), identity.role
    )


async def authorize(
    db: AsyncSession, raw_token: str | None, scope_domain: str, action: str
) -> VoiceDecision:
    """Resolve the token and authorize *action* ("read"/"write") on
    ``scope_domain``, returning the tier it resolved to.

    Effective permission is min(token, ceiling) under read < propose < write —
    the same arithmetic the MCP path does, so a household that configured
    approval for to-dos gets it on the speaker too, without configuring anything
    twice. A write that lands on ``propose`` is neither done nor refused: the
    caller records a proposal and says so out loud. Anything below that raises
    :class:`VoiceAuthError`.
    """
    pat, identity = await resolve_identity(db, raw_token)

    token = scope_tier(pat.scopes or {}, scope_domain)
    ceiling = await _member_ceiling_tier(db, identity, scope_domain, action)
    effective = min_tier(token, ceiling)

    floor = "read" if action == "read" else "propose"
    if tier_rank(effective) < tier_rank(floor):
        if tier_rank(token) <= tier_rank(ceiling):
            raise VoiceAuthError(
                f"Token lacks {action} access to {scope_domain}.", reason=DENIED
            )
        raise VoiceAuthError(
            f"Member lacks {_permission_action(action)} on {scope_domain}.",
            reason=DENIED,
        )
    return VoiceDecision(pat=pat, identity=identity, tier=effective, requested=action)
