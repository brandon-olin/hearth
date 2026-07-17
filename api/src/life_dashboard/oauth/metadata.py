"""Authorization-server metadata document (RFC 8414).

Served at ``/.well-known/oauth-authorization-server`` so a client (or an MCP
agent following the spec's discovery step) can learn the endpoint URLs and
supported parameters without out-of-band configuration. Consumer account-linking
setups usually take the endpoints by hand, but publishing the document keeps the
server spec-compliant and self-describing.
"""
from __future__ import annotations

from life_dashboard.oauth.scopes import SUPPORTED_SCOPE_STRINGS


def authorization_server_metadata(issuer: str) -> dict:
    """Build the RFC 8414 metadata for a given issuer (scheme://host base URL)."""
    base = issuer.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "scopes_supported": list(SUPPORTED_SCOPE_STRINGS),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
    }
