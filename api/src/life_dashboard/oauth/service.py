"""OAuth 2.1 authorization-server logic (security-007).

All OAuth database access and crypto lives here; the router stays thin and only
translates the errors below into HTTP/redirect responses. The flow:

  register_client → validate_authorization_request → issue_authorization_code
  → exchange_code (mints a scoped PAT via auth.pat_service.create_token)

The minted PAT *is* the OAuth access token, so every request it makes afterwards
authorizes through the same path as a directly-issued PAT — this layer adds an
issuance ceremony, never a second authorization model.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import PersonalAccessToken
from life_dashboard.auth.pat_scopes import PAT_SCOPE_LABELS
from life_dashboard.auth.pat_service import PATError, create_token
from life_dashboard.oauth.models import OAuthAuthorizationCode, OAuthClient
from life_dashboard.oauth.scopes import OAuthScopeError, parse_scope, to_scope_string

logger = logging.getLogger(__name__)

#: Client-id / client-secret prefixes — greppable in logs, catchable by secret
#: scanners, and told apart from PATs at a glance.
_CLIENT_ID_PREFIX = "hearth_client_"
_CLIENT_SECRET_PREFIX = "hearth_secret_"

#: Authorization codes are single-use and short-lived. OAuth 2.1 caps the
#: lifetime at 10 minutes; 5 is plenty for a redirect round-trip and halves the
#: replay window.
_CODE_TTL_SECONDS = 300

#: PKCE (RFC 7636 §4.1) verifier length bounds.
_MIN_VERIFIER_LEN = 43
_MAX_VERIFIER_LEN = 128

#: Confidential-client auth methods that carry a secret. "none" is a public
#: client (PKCE-only) per the OAuth 2.1 default.
_CONFIDENTIAL_AUTH_METHODS = frozenset({"client_secret_post", "client_secret_basic"})

#: The only grant + PKCE method this server implements. OAuth 2.1 forbids the
#: "plain" challenge method, so S256 is the sole option.
_SUPPORTED_GRANT_TYPES = frozenset({"authorization_code"})
_SUPPORTED_CHALLENGE_METHODS = frozenset({"S256"})


class OAuthError(Exception):
    """A flow step failed. ``error`` is an RFC 6749 error code; ``description``
    is a safe-to-return human string. The router maps these to a JSON error
    body (token/registration endpoints) or a redirect with error params
    (authorize endpoint).
    """

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
        self.status_code = status_code


def _sha256(raw: str) -> str:
    """Hex SHA-256 — the storage form for client secrets and auth codes.

    The inputs are high-entropy CSPRNG output (not passwords), so a fast hash is
    correct here for the same reason PATs use SHA-256: no dictionary to attack,
    and it keeps the indexed code lookup fast. Mirrors auth.pat_service."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _as_aware(dt: datetime) -> datetime:
    """Assume UTC for a naive datetime (SQLite/psycopg2 can hand these back)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_valid_redirect_uri(uri: str) -> bool:
    """A redirect URI must be an absolute https URL, or http on a loopback host
    for local development. Anything else (custom schemes, wildcards, fragments)
    is refused — a lax redirect allow-list is how OAuth deployments leak codes.
    """
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    if parsed.fragment or not parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme == "http":
        host = (parsed.hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1")
    return False


# ── Dynamic client registration (RFC 7591) ────────────────────────────────────

async def register_client(
    db: AsyncSession,
    *,
    client_name: str,
    redirect_uris: list[str],
    token_endpoint_auth_method: str,
    grant_types: list[str],
    scope: str | None,
) -> tuple[OAuthClient, str | None]:
    """Register a client and return (record, raw_secret).

    ``raw_secret`` is None for public clients and is otherwise returned exactly
    once — only its hash is stored. Raises OAuthError with the RFC 7591
    ``invalid_client_metadata`` / ``invalid_redirect_uri`` codes on bad input.
    """
    if not redirect_uris or not all(_is_valid_redirect_uri(u) for u in redirect_uris):
        raise OAuthError(
            "invalid_redirect_uri",
            "Every redirect_uri must be an absolute https URL (http is allowed "
            "only for localhost).",
        )

    if token_endpoint_auth_method not in ({"none"} | _CONFIDENTIAL_AUTH_METHODS):
        raise OAuthError(
            "invalid_client_metadata",
            "token_endpoint_auth_method must be one of: none, client_secret_post, "
            "client_secret_basic.",
        )

    unsupported = set(grant_types) - _SUPPORTED_GRANT_TYPES
    if unsupported:
        raise OAuthError(
            "invalid_client_metadata",
            f"Unsupported grant_types: {', '.join(sorted(unsupported))}. "
            "Only authorization_code is supported.",
        )

    # If the client declared a scope up front, validate it now so registration
    # fails fast rather than at the authorize step.
    if scope:
        try:
            parse_scope(scope)
        except OAuthScopeError as exc:
            raise OAuthError("invalid_client_metadata", str(exc)) from exc

    raw_secret: str | None = None
    secret_hash: str | None = None
    if token_endpoint_auth_method in _CONFIDENTIAL_AUTH_METHODS:
        raw_secret = f"{_CLIENT_SECRET_PREFIX}{secrets.token_urlsafe(32)}"
        secret_hash = _sha256(raw_secret)

    client = OAuthClient(
        client_id=f"{_CLIENT_ID_PREFIX}{secrets.token_urlsafe(18)}",
        client_secret_hash=secret_hash,
        client_name=client_name,
        redirect_uris=list(redirect_uris),
        token_endpoint_auth_method=token_endpoint_auth_method,
        grant_types=list(grant_types),
        scope=scope,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    logger.info(
        "OAuth client registered: client_id=%s method=%s",
        client.client_id,
        token_endpoint_auth_method,
    )
    return client, raw_secret


async def get_client(db: AsyncSession, client_id: str) -> OAuthClient | None:
    result = await db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))
    return result.scalar_one_or_none()


# ── Authorization endpoint ─────────────────────────────────────────────────────

async def validate_authorization_request(
    db: AsyncSession,
    *,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    scope: str | None,
    code_challenge: str | None,
    code_challenge_method: str,
) -> tuple[OAuthClient, dict[str, str]]:
    """Validate an authorization request. Returns (client, parsed_pat_scopes).

    Order matters: the client and redirect_uri are checked *first*, because
    until we know the redirect_uri is one the client registered we must not
    redirect errors back to it (that would make us an open error-redirector).
    Once those pass, later errors can be safely reported via the redirect_uri.

    Raises OAuthError; the caller decides whether to render it or redirect it.
    """
    client = await get_client(db, client_id)
    if client is None:
        raise OAuthError("invalid_client", "Unknown client_id.", status_code=400)

    # Exact match against the registered allow-list — no prefix/substring games.
    if redirect_uri not in (client.redirect_uris or []):
        raise OAuthError(
            "invalid_request",
            "redirect_uri does not match a registered redirect URI for this client.",
            status_code=400,
        )

    # ── From here, errors are safe to redirect back to redirect_uri ───────────
    if response_type != "code":
        raise OAuthError(
            "unsupported_response_type",
            "Only the authorization-code flow (response_type=code) is supported.",
        )

    # OAuth 2.1 requires PKCE for every authorization-code request.
    if not code_challenge:
        raise OAuthError("invalid_request", "code_challenge is required (PKCE).")
    if code_challenge_method not in _SUPPORTED_CHALLENGE_METHODS:
        raise OAuthError(
            "invalid_request",
            "code_challenge_method must be S256 (the 'plain' method is not allowed).",
        )

    try:
        pat_scopes = parse_scope(scope)
    except OAuthScopeError as exc:
        raise OAuthError("invalid_scope", str(exc)) from exc

    return client, pat_scopes


def describe_scopes(pat_scopes: dict[str, str]) -> list[str]:
    """Human-readable "<label> (read|write)" lines for the consent screen."""
    return [
        f"{PAT_SCOPE_LABELS.get(domain, domain)} ({level})"
        for domain, level in sorted(pat_scopes.items())
    ]


async def issue_authorization_code(
    db: AsyncSession,
    *,
    client: OAuthClient,
    user_id: uuid.UUID,
    redirect_uri: str,
    scope: str,
    code_challenge: str,
    code_challenge_method: str,
) -> str:
    """Mint a single-use authorization code and return the raw value.

    Only the SHA-256 is stored. The granted `scope` is normalised through
    parse_scope/to_scope_string so what we persist is exactly what the token
    endpoint will grant."""
    pat_scopes = parse_scope(scope)  # re-validate; callers pass the raw request scope
    normalised_scope = to_scope_string(pat_scopes)

    raw_code = secrets.token_urlsafe(32)
    code = OAuthAuthorizationCode(
        code_hash=_sha256(raw_code),
        client_id=client.client_id,
        user_id=user_id,
        redirect_uri=redirect_uri,
        scope=normalised_scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=_CODE_TTL_SECONDS),
    )
    db.add(code)
    await db.commit()
    logger.info(
        "OAuth authorization code issued: client_id=%s user=%s", client.client_id, user_id
    )
    return raw_code


def build_redirect(redirect_uri: str, params: dict[str, str | None]) -> str:
    """Append query parameters to a redirect URI, dropping None values.

    Uses '&' if the URI already has a query string, '?' otherwise — a
    registered redirect_uri is allowed to carry its own static query."""
    query = urlencode({k: v for k, v in params.items() if v is not None})
    if not query:
        return redirect_uri
    sep = "&" if urlparse(redirect_uri).query else "?"
    return f"{redirect_uri}{sep}{query}"


# ── Token endpoint ─────────────────────────────────────────────────────────────

def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """RFC 7636 S256: base64url(sha256(verifier)) == challenge, no padding.

    Compared with a constant-time equality to avoid leaking the challenge one
    byte at a time through timing."""
    # RFC 7636 §4.1: the verifier is 43–128 characters from an ASCII-only
    # alphabet. A wrong length or a non-ASCII byte is simply a failed
    # verification, not a server error — return False so it flows into the
    # normal invalid_grant path rather than raising UnicodeEncodeError.
    if not (_MIN_VERIFIER_LEN <= len(code_verifier) <= _MAX_VERIFIER_LEN):
        return False
    if not code_verifier.isascii():
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, code_challenge)


async def _authenticate_client(
    db: AsyncSession, client_id: str | None, client_secret: str | None
) -> OAuthClient:
    """Resolve and authenticate the client at the token endpoint.

    Public clients (auth method "none") present no secret and rely on PKCE.
    Confidential clients must present the secret they registered with."""
    if not client_id:
        raise OAuthError("invalid_client", "client_id is required.", status_code=401)
    client = await get_client(db, client_id)
    if client is None:
        raise OAuthError("invalid_client", "Unknown client_id.", status_code=401)

    if client.token_endpoint_auth_method in _CONFIDENTIAL_AUTH_METHODS:
        if not client_secret or client.client_secret_hash is None or not secrets.compare_digest(
            _sha256(client_secret), client.client_secret_hash
        ):
            raise OAuthError("invalid_client", "Client authentication failed.", status_code=401)
    return client


async def exchange_code(
    db: AsyncSession,
    *,
    grant_type: str,
    code: str | None,
    redirect_uri: str | None,
    code_verifier: str | None,
    client_id: str | None,
    client_secret: str | None,
    minted_token_expiry_days: int | None,
) -> tuple[str, str, int | None]:
    """Exchange an authorization code for a scoped PAT.

    Returns (raw_pat, granted_scope_string, expires_in_seconds_or_None). Raises
    OAuthError on any failure. The code is consumed atomically (UPDATE … WHERE
    used_at IS NULL RETURNING) so a replayed or double-submitted code can mint
    at most one token — the second exchange loses the race and gets
    invalid_grant.
    """
    if grant_type not in _SUPPORTED_GRANT_TYPES:
        raise OAuthError(
            "unsupported_grant_type",
            f"grant_type must be one of: {', '.join(sorted(_SUPPORTED_GRANT_TYPES))}.",
        )
    client = await _authenticate_client(db, client_id, client_secret)

    if not code or not code_verifier or not redirect_uri:
        raise OAuthError(
            "invalid_request", "code, redirect_uri, and code_verifier are all required."
        )

    row = (
        await db.execute(
            select(OAuthAuthorizationCode).where(
                OAuthAuthorizationCode.code_hash == _sha256(code)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise OAuthError("invalid_grant", "Authorization code is invalid.")

    # Bind the code to the presenting client and the original redirect_uri
    # before spending it. A mismatch means the code was intercepted or replayed
    # by a different client.
    if row.client_id != client.client_id:
        raise OAuthError("invalid_grant", "Authorization code was issued to another client.")
    if row.redirect_uri != redirect_uri:
        raise OAuthError("invalid_grant", "redirect_uri does not match the authorization request.")
    if row.used_at is not None:
        raise OAuthError("invalid_grant", "Authorization code has already been used.")
    if _as_aware(row.expires_at) <= datetime.now(timezone.utc):
        raise OAuthError("invalid_grant", "Authorization code has expired.")
    if not _verify_pkce(code_verifier, row.code_challenge):
        raise OAuthError("invalid_grant", "PKCE verification failed.")

    # Consume the code atomically, then commit it *before* minting — only the
    # request that flips used_at proceeds, and the code is definitively spent
    # even if minting then fails. A concurrent replay that loses this race sees
    # used_at already set and gets invalid_grant.
    consumed = (
        await db.execute(
            update(OAuthAuthorizationCode)
            .where(
                OAuthAuthorizationCode.id == row.id,
                OAuthAuthorizationCode.used_at.is_(None),
            )
            .values(used_at=datetime.now(timezone.utc))
            .returning(OAuthAuthorizationCode.id)
        )
    ).scalar_one_or_none()
    if consumed is None:
        await db.rollback()
        raise OAuthError("invalid_grant", "Authorization code has already been used.")
    await db.commit()

    # Mint the scoped PAT the whole system already understands. The token name
    # records which client the grant came from so it's identifiable in the
    # member's token-management UI and revocable there. If minting fails (e.g.
    # the member is at their token limit) the code stays spent — the client must
    # restart the flow, which is the safe, replay-proof direction.
    pat_scopes = parse_scope(row.scope)
    try:
        _pat, raw_pat = await create_token(
            db,
            user_id=row.user_id,
            name=f"OAuth: {client.client_name}",
            scopes=pat_scopes,
            expires_in_days=minted_token_expiry_days,
        )
    except PATError as exc:
        await db.rollback()
        raise OAuthError("invalid_scope", str(exc), status_code=400) from exc

    expires_in = (
        minted_token_expiry_days * 24 * 60 * 60 if minted_token_expiry_days is not None else None
    )
    return raw_pat, to_scope_string(pat_scopes), expires_in


async def _load_pat(db: AsyncSession, pat_id: uuid.UUID) -> PersonalAccessToken | None:
    """Test/utility helper — fetch a minted PAT by id."""
    return (
        await db.execute(select(PersonalAccessToken).where(PersonalAccessToken.id == pat_id))
    ).scalar_one_or_none()
