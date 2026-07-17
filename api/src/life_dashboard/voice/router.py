"""Alexa skill webhook (voice-002).

A single endpoint, ``POST /voice/alexa``, that the Alexa custom skill (or a thin
Lambda in front of it) calls with the Alexa Skills Kit JSON envelope. The flow:

  1. **Verify the request is really from Amazon** (cloud tier / when enabled):
     the RSA signature over the raw body, plus a fresh timestamp. A forged or
     replayed request is rejected with a non-200 before any parsing.
  2. **Verify it names this skill** — applicationId must match ``alexa_skill_id``
     when configured. Cheap and always run.
  3. **Dispatch** the intent to a spoken response (service.dispatch), which
     authorizes the account-linking PAT and calls the domain services.

Security checks return a bare HTTP error (Amazon treats non-200 as failure);
everything a *user* should hear — "link your account", "no permission", "added
milk" — is a 200 with speech built in the service layer.

No IP rate limit is applied here: all Alexa traffic egresses from shared AWS
addresses, so an IP limit would throttle unrelated households together. Abuse is
bounded per-token instead (cloud tier) in voice.auth, mirroring the MCP path.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.core.database import get_db
from life_dashboard.core.settings import settings
from life_dashboard.voice import service
from life_dashboard.voice.schemas import AlexaEnvelope
from life_dashboard.voice.signature import (
    AlexaVerificationError,
    check_application_id,
    check_timestamp,
    verify_signature,
)

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/alexa")
async def alexa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle one Alexa request and return the spoken response."""
    raw_body = await request.body()

    # 1. Cryptographic verification — only when enabled (needs S3 network egress).
    if settings.alexa_verify_signature:
        try:
            await verify_signature(
                raw_body,
                request.headers.get("SignatureCertChainUrl", ""),
                request.headers.get("Signature", ""),
            )
        except AlexaVerificationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    # 2. Parse. A malformed body can't be a real Alexa request.
    try:
        envelope = AlexaEnvelope.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed Alexa request"
        ) from exc

    # 3. This-skill + freshness checks (freshness only when verification is on, so
    #    a static-timestamp test fixture isn't rejected off the cloud tier).
    try:
        check_application_id(envelope.application_id, settings.alexa_skill_id)
        if settings.alexa_verify_signature:
            check_timestamp(envelope.request.timestamp)
    except AlexaVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # 4. Dispatch to a spoken response.
    response = await service.dispatch(db, envelope)
    return JSONResponse(response)
