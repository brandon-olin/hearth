"""Webhook subscription management — Settings → Integrations → Webhooks.

Mounted at ``/webhooks``. Deliberately mapped to NO PAT scope domain (see
auth/pat_scopes.py): the deny-by-default path rule means a personal access token
cannot reach these routes, so a token can never mint itself a new egress channel
for household data. Management from an agent is webhook-002, behind an explicit
scope; the agent-facing surface this build ships is the outbound event itself.

The signing secret is returned exactly once, in the create response. It is not
readable afterwards through any route — losing it means deleting the
subscription and creating a new one.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db
from life_dashboard.webhooks import service, ssrf, summaries
from life_dashboard.webhooks.schemas import (
    WebhookEventCatalogResponse,
    WebhookEventInfo,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionListResponse,
    WebhookSubscriptionResponse,
    WebhookSubscriptionUpdate,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/events", response_model=WebhookEventCatalogResponse)
async def list_event_catalog(
    current_user: User = Depends(get_current_user),
) -> WebhookEventCatalogResponse:
    """The deliverable event catalog, with the exact summary fields each carries.

    Publishing the allowlist is intentional: a subscriber should be able to see
    what a payload can contain before pointing it anywhere."""
    return WebhookEventCatalogResponse(
        items=[
            WebhookEventInfo(
                event=event,
                description=summaries.EVENT_DESCRIPTIONS[event],
                summary_fields=list(summaries.EVENT_SUMMARY_FIELDS[event]),
            )
            for event in summaries.CATALOG
        ]
    )


@router.get("", response_model=WebhookSubscriptionListResponse)
async def list_subscriptions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookSubscriptionListResponse:
    return await service.list_subscriptions(db, current_user.household_id)


@router.post(
    "",
    response_model=WebhookSubscriptionCreated,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_subscription(
    data: WebhookSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookSubscriptionCreated:
    """Create a subscription owned by the calling member.

    The response carries the signing secret — the only time it is ever returned.
    """
    try:
        return await service.create_subscription(
            db, current_user.household_id, current_user.id, data
        )
    except service.WebhookEncryptionUnavailable as exc:
        # 503, not 400: the request is fine, the install is not configured to
        # hold a secret safely yet.
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except service.DuplicateWebhookTarget as exc:
        # 409: a retried create must not leave a second permanent egress channel.
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ssrf.WebhookTargetRejected as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.patch("/{subscription_id}", response_model=WebhookSubscriptionResponse)
async def update_subscription(
    subscription_id: uuid.UUID,
    data: WebhookSubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookSubscriptionResponse:
    """Pause, resume, relabel, or change which events a subscription receives."""
    try:
        updated = await service.update_subscription(
            db, subscription_id, current_user.household_id, current_user.id, data
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Webhook subscription not found"
        )
    return updated


@router.delete("/{subscription_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_subscription(
        db, subscription_id, current_user.household_id, current_user.id
    )
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Webhook subscription not found"
        )
