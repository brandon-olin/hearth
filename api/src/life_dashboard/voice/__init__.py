"""Voice-platform surface for Hearth (voice-002).

An Alexa custom skill drives core household actions by voice. The skill (or a
thin Lambda in front of it) POSTs Amazon's Alexa Skills Kit JSON envelope to
``POST /voice/alexa``; the request carries the household member's OAuth-minted
Personal Access Token as the account-linking ``accessToken`` (security-007), so
every intent authorizes exactly like an MCP tool call or a hand-pasted PAT:
token scope ∩ owning-member ceiling. The four intents map onto the same domain
services the MCP write tools use, so the voice surface adds a transport, not a
second copy of the business rules.
"""
from life_dashboard.voice.router import router

__all__ = ["router"]
