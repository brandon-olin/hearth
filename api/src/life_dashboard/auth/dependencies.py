import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import Household, HouseholdMembership, PersonalAccessToken, User
from life_dashboard.auth.pat_rate_limit import check_rate_limit
from life_dashboard.auth.pat_scopes import (
    SCOPE_TO_PERMISSION_DOMAIN,
    check_scope,
    is_pat,
    resolve_required_scope,
)
from life_dashboard.auth.pat_service import authenticate_token
from life_dashboard.auth.service import get_user_by_id
from life_dashboard.auth.tokens import JWTError, decode_access_token
from life_dashboard.core.database import get_db
from life_dashboard.core.permissions import check_permission, load_household_permissions
from life_dashboard.core.settings import settings

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _enforce_pat_rate_limit(pat: PersonalAccessToken) -> None:
    """Cloud-tier per-token throttle (security-007). Raises 429 when the token
    exceeds its per-window budget. No-op on local/self-hosted, where the caller
    is a trusted household — see auth/pat_rate_limit.py."""
    if settings.deployment_tier != "cloud":
        return
    if not check_rate_limit(pat.id, settings.pat_rate_limit_per_minute):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this token. Slow down and retry shortly.",
            headers={"Retry-After": "60"},
        )

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency — resolves a Bearer credential to a User.

    Accepts two credential kinds, told apart by the `hearth_pat_` prefix:

    * **Session JWT** — the web app's short-lived access token. Full access,
      subject to the household's own role gates.
    * **Personal Access Token** (security-006) — a long-lived agent credential.
      Additionally required to carry a scope covering this request, and can
      never exceed what its owning member may do (see _enforce_pat_scope).

    Also loads the user's household membership and attaches household_id
    as a Python attribute so domain routers can use current_user.household_id
    without an extra query.

    Import and use as `Depends(get_current_user)` in any protected route.
    Raises 401 if the credential is absent, malformed, expired, or revoked, and
    403 if a PAT is used outside its scopes.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise _UNAUTHENTICATED

    raw_token = auth_header.removeprefix("Bearer ")

    pat: PersonalAccessToken | None = None
    if is_pat(raw_token):
        pat = await authenticate_token(db, raw_token)
        if pat is None:
            raise _INVALID_CREDENTIALS
        _enforce_pat_rate_limit(pat)
        user_id = pat.user_id
    else:
        try:
            payload = decode_access_token(raw_token)
            subject: str | None = payload.get("sub")
            if not subject:
                raise JWTError("missing sub claim")
            user_id = uuid.UUID(subject)
        except (JWTError, ValueError):
            raise _INVALID_CREDENTIALS

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(HouseholdMembership).where(HouseholdMembership.user_id == user_id)
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no household membership",
        )

    # Attach as plain Python attributes — not ORM columns, never written to DB.
    user.household_id = membership.household_id  # type: ignore[attr-defined]
    user.role = membership.role.value  # type: ignore[attr-defined]
    # ai-access-001: surface the per-membership AI gate so /auth/me payloads
    # carry it and the frontend knows whether to render AI surfaces.
    user.ai_features_enabled = membership.ai_features_enabled  # type: ignore[attr-defined]

    # security-006: how this request authenticated. "web" | "pat".
    # The audit wiring in plans/open-hearth/mcp-server.md reads these to
    # attribute a write to a specific token rather than just a member.
    user.auth_source = "pat" if pat else "web"  # type: ignore[attr-defined]
    user.pat_id = pat.id if pat else None  # type: ignore[attr-defined]

    if pat is not None:
        await _enforce_pat_scope(db, request, pat, user)

    household_result = await db.execute(
        select(Household).where(Household.id == membership.household_id)
    )
    household = household_result.scalar_one_or_none()
    user.household_name = household.name if household else None  # type: ignore[attr-defined]

    return user


async def _enforce_pat_scope(
    db: AsyncSession,
    request: Request,
    pat: PersonalAccessToken,
    user: User,
) -> None:
    """Authorize a PAT-authenticated request. Raises 403 if not permitted.

    Two layers, both must pass:

      1. **Token scope** — the token was granted read/write on this domain.
      2. **Member ceiling** — the owning member could do this themselves in
         the app. A restricted member's token is restricted too, which is what
         makes it safe to hand a kid's bedroom speaker a token.

    Paths that map to no scope domain are refused outright — see the
    deny-by-default rationale in pat_scopes.py.
    """
    required = resolve_required_scope(request.url.path, request.method)
    if required is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is not accessible with a personal access token.",
        )

    domain, action = required
    if not check_scope(pat.scopes or {}, domain, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token does not have {action} access to {domain}.",
        )

    # ── Layer 2: the owning member's own ceiling ──────────────────────────────
    permission_domain = SCOPE_TO_PERMISSION_DOMAIN.get(domain)
    if permission_domain is None:
        # No configurable household permission for this domain; the router's
        # own role gate remains the ceiling.
        return

    permissions = await load_household_permissions(db, user.household_id)  # type: ignore[attr-defined]
    # "write" maps to "create" — the coarsest write permission the config
    # models. Per-item ownership (manage_others) stays the router's job.
    permission_action = "read" if action == "read" else "create"
    if not check_permission(permissions, permission_domain, permission_action, user.role):  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Your account does not have {permission_action} permission "
                f"for {permission_domain}. A token cannot exceed its owner's access."
            ),
        )


# ai-access-001: dependency that gates AI surfaces on the per-member toggle.
# Add as `Depends(require_ai_enabled)` to any endpoint that needs to honor
# the admin's "AI off for this account" decision.
async def require_ai_enabled(
    current_user: "User" = Depends(get_current_user),
) -> "User":
    """Raise 403 when the current user has AI features disabled by their
    household admin. Otherwise behaves identically to get_current_user.

    Idempotent: layering this onto an endpoint that already depends on
    get_current_user is fine — FastAPI resolves the shared dependency once.
    """
    if not getattr(current_user, "ai_features_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "AI features are disabled for your account by your "
                "household admin. Ask an admin to enable them in "
                "Settings → Household."
            ),
        )
    return current_user
