"""Alexa Skills Kit request/response envelopes (voice-002).

Only the fields Hearth reads are modelled; ``extra="ignore"`` lets the rest of
Amazon's large envelope pass through untouched, so the parser never breaks when
Amazon adds fields. Alexa uses PascalCase (``System``) and camelCase
(``accessToken``, ``applicationId``) keys, declared as aliases so the code reads
in snake_case. Response builders return plain dicts in the strict ASK response
shape, centralised here rather than hand-assembled at each call site.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AlexaSlot(_Lenient):
    name: str
    value: str | None = None


class AlexaIntent(_Lenient):
    name: str
    slots: dict[str, AlexaSlot] = {}


class AlexaRequest(_Lenient):
    type: str
    request_id: str | None = Field(default=None, alias="requestId")
    timestamp: datetime | None = None
    locale: str | None = None
    intent: AlexaIntent | None = None
    reason: str | None = None


class _AlexaApplication(_Lenient):
    application_id: str | None = Field(default=None, alias="applicationId")


class _AlexaUser(_Lenient):
    access_token: str | None = Field(default=None, alias="accessToken")


class _AlexaSystem(_Lenient):
    application: _AlexaApplication | None = None
    user: _AlexaUser | None = None


class _AlexaContext(_Lenient):
    system: _AlexaSystem | None = Field(default=None, alias="System")


class _AlexaSession(_Lenient):
    user: _AlexaUser | None = None


class AlexaEnvelope(_Lenient):
    """The top-level request Amazon POSTs to the skill endpoint."""

    version: str = "1.0"
    session: _AlexaSession | None = None
    context: _AlexaContext | None = None
    request: AlexaRequest

    @property
    def access_token(self) -> str | None:
        """The account-linking token, from context (current) or session (older
        clients). Either location is where a linked Hearth PAT arrives."""
        if self.context and self.context.system and self.context.system.user:
            if self.context.system.user.access_token:
                return self.context.system.user.access_token
        if self.session and self.session.user and self.session.user.access_token:
            return self.session.user.access_token
        return None

    @property
    def application_id(self) -> str | None:
        if self.context and self.context.system and self.context.system.application:
            return self.context.system.application.application_id
        return None


# ── Response builders ─────────────────────────────────────────────────────────

def speak(text: str, *, end_session: bool = True, reprompt: str | None = None) -> dict:
    """A plain-text spoken response. ``end_session=False`` keeps the mic open for
    a follow-up (used by Launch/Help); ``reprompt`` is spoken if the user then
    stays silent."""
    response: dict = {
        "outputSpeech": {"type": "PlainText", "text": text},
        "shouldEndSession": end_session,
    }
    if reprompt is not None:
        response["reprompt"] = {
            "outputSpeech": {"type": "PlainText", "text": reprompt}
        }
    return {"version": "1.0", "response": response}


def link_account(text: str) -> dict:
    """A spoken response carrying a LinkAccount card, which surfaces a "link your
    Hearth account" button in the Alexa app. Used when no token is present or the
    token no longer works, so the user is told exactly how to recover."""
    envelope = speak(text, end_session=True)
    envelope["response"]["card"] = {"type": "LinkAccount"}
    return envelope
