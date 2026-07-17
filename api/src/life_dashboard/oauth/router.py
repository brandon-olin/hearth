"""OAuth 2.1 authorization-server endpoints (security-007).

  POST /oauth/register  — dynamic client registration (RFC 7591), public
  GET  /oauth/authorize — validate a request, return consent details (session)
  POST /oauth/authorize — record the user's consent, return the redirect (session)
  POST /oauth/token     — exchange an auth code for a scoped PAT (RFC 6749 §4.1)

The whole surface is cloud-tier only — ``require_cloud_tier`` returns 404 on
local/self-hosted so those tiers never expose OAuth and continue to paste a PAT
directly. The router is intentionally thin: every decision lives in
oauth/service.py, and the errors it raises are translated to OAuth's wire
formats (JSON error bodies, or a redirect carrying error params) here.
"""
from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.core.rate_limit import limiter
from life_dashboard.core.settings import settings
from life_dashboard.oauth import service
from life_dashboard.oauth.schemas import (
    AuthorizationDecision,
    AuthorizationDetails,
    AuthorizationRedirect,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    TokenGrantResponse,
)
from life_dashboard.oauth.service import OAuthError

router = APIRouter(prefix="/oauth", tags=["oauth"])


async def require_cloud_tier() -> None:
    """Gate the OAuth surface to the cloud tier.

    Read live from settings (not captured at import) so tests can flip the tier.
    A 404 — rather than 403 — keeps the endpoints invisible on local/self-hosted:
    those tiers behave as if OAuth does not exist, which is exactly the
    'directly-pasted PAT, no OAuth requirement' contract for security-007.
    """
    if settings.deployment_tier != "cloud":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )


def _oauth_error_response(exc: OAuthError) -> JSONResponse:
    """RFC 6749 §5.2 JSON error body. 401s carry a Bearer challenge header."""
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "error_description": exc.description},
        headers=headers,
    )


# ── Dynamic client registration ────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=ClientRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cloud_tier)],
)
@limiter.limit("10/hour")
async def register_client(
    request: Request,
    body: ClientRegistrationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register an OAuth client (RFC 7591). Open registration, rate-limited per
    IP. The client_secret (confidential clients only) is returned once here."""
    try:
        client, raw_secret = await service.register_client(
            db,
            client_name=body.client_name,
            redirect_uris=body.redirect_uris,
            token_endpoint_auth_method=body.token_endpoint_auth_method,
            grant_types=body.grant_types,
            scope=body.scope,
        )
    except OAuthError as exc:
        return _oauth_error_response(exc)

    return ClientRegistrationResponse(
        client_id=client.client_id,
        client_secret=raw_secret,
        client_id_issued_at=int(client.created_at.timestamp()),
        client_name=client.client_name,
        redirect_uris=client.redirect_uris,
        token_endpoint_auth_method=client.token_endpoint_auth_method,
        grant_types=client.grant_types,
    )


# ── Authorization endpoint ─────────────────────────────────────────────────────

@router.get(
    "/authorize",
    response_model=AuthorizationDetails,
    dependencies=[Depends(require_cloud_tier)],
)
async def authorize_details(
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    scope: str | None = None,
    state: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str = "S256",
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate an authorization request and return what a consent screen needs.

    Requires a logged-in session (the consenting member). Invalid requests are
    reported as JSON here rather than redirected — the frontend has not yet sent
    the browser onward, so there is nothing to redirect."""
    try:
        client, pat_scopes = await service.validate_authorization_request(
            db,
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )
    except OAuthError as exc:
        return _oauth_error_response(exc)

    return AuthorizationDetails(
        client_id=client.client_id,
        client_name=client.client_name,
        redirect_uri=redirect_uri,
        scope=service.to_scope_string(pat_scopes),
        scope_descriptions=service.describe_scopes(pat_scopes),
        state=state,
        code_challenge=code_challenge or "",
        code_challenge_method=code_challenge_method,
    )


@router.post(
    "/authorize",
    response_model=AuthorizationRedirect,
    dependencies=[Depends(require_cloud_tier)],
)
async def authorize_decision(
    body: AuthorizationDecision,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the member's approve/deny decision and return the redirect URL.

    On approval, mints a single-use authorization code and returns the client's
    redirect_uri with ``code`` + ``state``. On denial, returns the redirect with
    ``error=access_denied`` (RFC 6749 §4.1.2.1). The request is re-validated
    server-side — nothing is trusted from the echoed body until the client and
    redirect_uri check out."""
    try:
        client, _pat_scopes = await service.validate_authorization_request(
            db,
            response_type="code",
            client_id=body.client_id,
            redirect_uri=body.redirect_uri,
            scope=body.scope,
            code_challenge=body.code_challenge,
            code_challenge_method=body.code_challenge_method,
        )
    except OAuthError as exc:
        return _oauth_error_response(exc)

    if not body.approved:
        return AuthorizationRedirect(
            redirect_url=service.build_redirect(
                body.redirect_uri, {"error": "access_denied", "state": body.state}
            )
        )

    raw_code = await service.issue_authorization_code(
        db,
        client=client,
        user_id=user.id,
        redirect_uri=body.redirect_uri,
        scope=body.scope,
        code_challenge=body.code_challenge,
        code_challenge_method=body.code_challenge_method,
    )
    return AuthorizationRedirect(
        redirect_url=service.build_redirect(
            body.redirect_uri, {"code": raw_code, "state": body.state}
        )
    )


# ── Token endpoint ─────────────────────────────────────────────────────────────

def _client_credentials_from_basic(request: Request) -> tuple[str | None, str | None]:
    """Extract client_id/secret from an HTTP Basic Authorization header, if any.

    RFC 6749 §2.3.1 — confidential clients may authenticate with
    ``Authorization: Basic base64(client_id:client_secret)`` instead of form
    fields. Returns (None, None) when the header is absent or unparseable so the
    form fields remain the fallback."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None, None
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None, None
    client_id, sep, client_secret = decoded.partition(":")
    if not sep:
        return None, None
    return client_id or None, client_secret or None


@router.post("/token", dependencies=[Depends(require_cloud_tier)])
@limiter.limit("60/minute")
async def token(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Exchange an authorization code for a scoped PAT (RFC 6749 §4.1.3).

    Accepts form-encoded parameters (the OAuth standard) and both client
    authentication styles — ``client_secret_post`` form fields or a
    ``client_secret_basic`` Authorization header. On success returns the PAT as
    the ``access_token``; the client uses it as a Bearer credential exactly like
    a hand-pasted PAT."""
    basic_id, basic_secret = _client_credentials_from_basic(request)
    resolved_client_id = client_id or basic_id
    resolved_client_secret = client_secret or basic_secret

    try:
        raw_pat, granted_scope, expires_in = await service.exchange_code(
            db,
            grant_type=grant_type,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            client_id=resolved_client_id,
            client_secret=resolved_client_secret,
            minted_token_expiry_days=settings.oauth_minted_token_expiry_days,
        )
    except OAuthError as exc:
        return _oauth_error_response(exc)

    return TokenGrantResponse(
        access_token=raw_pat, scope=granted_scope, expires_in=expires_in
    )
