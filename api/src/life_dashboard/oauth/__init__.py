"""OAuth 2.1 authorization server layered in front of Personal Access Tokens.

security-007 / plans/open-hearth/mcp-server.md.

Hosted agent UIs and consumer voice platforms (Alexa/Google account linking, a
"Connect Hearth" button) expect an OAuth 2.1 authorization-code + PKCE flow with
dynamic client registration rather than a hand-pasted Bearer token. This package
puts that flow in front of the existing PAT primitive (security-006): a completed
grant mints a scoped PAT under the hood and returns it as the OAuth access token,
so every downstream request authorizes through the exact same code path as a
directly-issued PAT (member ceiling ∩ token scope). No new authorization model.

Cloud-tier only. Local and self-hosted installs continue to paste a PAT directly
and never see these endpoints (see auth requirement in the router's tier gate).
"""
