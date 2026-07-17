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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import Household, HouseholdMembership, PersonalAccessToken
from life_dashboard.auth.pat_rate_limit import check_rate_limit
from life_dashboard.auth.pat_scopes import (
    SCOPE_TO_PERMISSION_DOMAIN,
    check_scope,
    is_pat,
)
from life_dashboard.auth.pat_service import authenticate_token
from life_dashboard.auth.service import get_user_by_id
from life_dashboard.core.permissions import check_permission, load_household_permissions
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


async def _within_member_ceiling(
    db: AsyncSession, identity: PatIdentity, scope_domain: str, action: str
) -> bool:
    """Layer 2 — is *action* on ``scope_domain`` within the owning member's own
    ceiling? Only domains with a configurable household permission are checked."""
    permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(scope_domain)
    if permission_domain is None:
        return True
    permissions = await load_household_permissions(db, identity.household_id)
    return check_permission(
        permissions, permission_domain, _permission_action(action), identity.role
    )


async def authorize(
    db: AsyncSession, raw_token: str | None, scope_domain: str, action: str
) -> tuple[PersonalAccessToken, PatIdentity]:
    """Resolve the token and authorize *action* ("read"/"write") on
    ``scope_domain``. Raises :class:`VoiceAuthError` on any failure."""
    pat, identity = await resolve_identity(db, raw_token)

    if not check_scope(pat.scopes or {}, scope_domain, action):
        raise VoiceAuthError(
            f"Token lacks {action} access to {scope_domain}.", reason=DENIED
        )
    if not await _within_member_ceiling(db, identity, scope_domain, action):
        raise VoiceAuthError(
            f"Member lacks {_permission_action(action)} on {scope_domain}.",
            reason=DENIED,
        )
    return pat, identity
