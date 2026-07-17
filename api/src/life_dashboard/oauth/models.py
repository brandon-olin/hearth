"""OAuth 2.1 authorization-server tables (security-007).

Two tables sit in front of the PAT primitive:

* ``oauth_clients`` — dynamically registered clients (RFC 7591). A consumer
  platform (Alexa/Google account linking) or a hosted "Connect Hearth" UI
  registers once and receives a ``client_id`` (+ a secret for confidential
  clients). Public clients hold no secret and must use PKCE.

* ``oauth_authorization_codes`` — short-lived, single-use codes bridging the
  authorize and token endpoints. Stored as a SHA-256 hash only (same reasoning
  as PATs and refresh tokens: a leaked table yields no usable codes), alongside
  the PKCE challenge the token exchange must satisfy.

There is deliberately no OAuth access-token table: the token endpoint mints a
Personal Access Token and returns *that* as the access token, so
``personal_access_tokens`` remains the single credential store the rest of the
system already understands and can revoke.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class OAuthClient(Base):
    """A dynamically registered OAuth client (RFC 7591).

    ``client_id`` is a non-secret public identifier. ``client_secret_hash`` is
    NULL for public clients (``token_endpoint_auth_method == "none"``), which
    are required to use PKCE; confidential clients store a SHA-256 of their
    secret and present it at the token endpoint.
    """
    __tablename__ = "oauth_clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    # Non-secret, client-facing identifier, e.g. "hearth_client_a1b2c3…".
    client_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    # SHA-256 of the client secret. NULL = public client (PKCE only).
    client_secret_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Exact-match allow-list of redirect URIs (list[str]) — a code is only ever
    # redirected to a URI registered here, which stops an open redirector.
    redirect_uris: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # "none" (public, PKCE) | "client_secret_post" | "client_secret_basic".
    token_endpoint_auth_method: Mapped[str] = mapped_column(
        String(40), nullable=False, default="none"
    )
    # Grant types this client may use. v1 supports "authorization_code" only.
    grant_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Space-delimited scope string the client registered an interest in (RFC
    # 7591 optional metadata). Advisory only — the authorize request's own
    # `scope` is what gets granted, still bounded by the member ceiling.
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OAuthAuthorizationCode(Base):
    """A single-use authorization code with its PKCE challenge (security-007).

    Issued by the authorize endpoint after the user consents, redeemed once at
    the token endpoint. ``used_at`` is set atomically on redemption so a
    replayed code cannot mint a second token.
    """
    __tablename__ = "oauth_authorization_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    # SHA-256 of the raw code. No plaintext column — same as PATs.
    code_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # The member who approved the grant; the minted PAT is owned by this user.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Must match the redirect_uri presented at the token endpoint (RFC 6749
    # §4.1.3) — a defence against code interception across registered URIs.
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    # Space-delimited granted scope string; parsed to a PAT blob at redemption.
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    # PKCE (RFC 7636): the token exchange must present a verifier whose SHA-256
    # base64url-encoding equals code_challenge. Method is always "S256".
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(10), nullable=False, default="S256")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
