"""Pydantic schemas for the OAuth 2.1 endpoints (security-007)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ── Dynamic client registration (RFC 7591) ────────────────────────────────────

class ClientRegistrationRequest(BaseModel):
    """RFC 7591 client metadata. Only the fields Hearth honours are modelled;
    unknown members are ignored so a spec-complete client can register."""
    model_config = ConfigDict(extra="ignore")

    client_name: str = Field(min_length=1, max_length=200)
    redirect_uris: list[str] = Field(min_length=1)
    # "none" (public client + PKCE) is the OAuth 2.1 default. Confidential
    # clients (Alexa/Google account linking) send "client_secret_post".
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code"])
    scope: str | None = None


class ClientRegistrationResponse(BaseModel):
    """RFC 7591 registration response. `client_secret` is present only for
    confidential clients and is returned exactly once, at registration."""
    client_id: str
    client_secret: str | None = None
    client_id_issued_at: int
    client_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str
    grant_types: list[str]


# ── Authorization endpoint ────────────────────────────────────────────────────

class AuthorizationDetails(BaseModel):
    """What a consent screen needs to render before the user approves.

    Returned by GET /oauth/authorize once the request has been validated. The
    frontend shows `client_name` requesting `scopes`, then POSTs approval back
    with the same request parameters echoed here."""
    client_id: str
    client_name: str
    redirect_uri: str
    scope: str
    # Human-readable "<label> (read|write)" lines for the consent UI.
    scope_descriptions: list[str]
    state: str | None = None
    code_challenge: str
    code_challenge_method: str


class AuthorizationDecision(BaseModel):
    """The consent submission. Echoes the validated request parameters plus the
    user's approve/deny choice. Re-validated server-side — nothing is trusted
    from a stored pending-authorization row because there is none."""
    client_id: str
    redirect_uri: str
    scope: str
    code_challenge: str
    code_challenge_method: str = "S256"
    state: str | None = None
    approved: bool = True


class AuthorizationRedirect(BaseModel):
    """The URL the browser should be sent to next — the client's redirect_uri
    with `code`+`state` on approval, or `error`+`state` on denial. Returned as
    JSON so an API caller (or the frontend consent page) can perform the
    redirect itself."""
    redirect_url: str


# ── Token endpoint ────────────────────────────────────────────────────────────

class TokenGrantResponse(BaseModel):
    """RFC 6749 §5.1 token response. `access_token` is a Hearth PAT; the whole
    system already knows how to authorize and revoke it."""
    access_token: str
    token_type: str = "Bearer"
    scope: str
    # Omitted when the minted PAT never expires (the long-lived, revocable
    # default for account linking). Present as a positive integer otherwise.
    expires_in: int | None = None
