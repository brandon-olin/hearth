"""Audit log service (security-008).

``record`` is the single write primitive; everything that wants to leave an
attributed trail — the MCP ``@audited`` decorator today, web routes later —
calls it. It is deliberately transaction-neutral: it ``add``s and ``flush``es
but does not commit, so a caller can record inside the same transaction as the
write it is describing (web routes) or in a dedicated session (the decorator).
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.audit.models import AuditLog
from life_dashboard.audit.schemas import AuditLogListResponse, AuditLogResponse, AuditSource


async def record(
    db: AsyncSession,
    *,
    household_id: uuid.UUID,
    source: AuditSource | str,
    action: str,
    entity_type: str,
    actor_user_id: uuid.UUID | None = None,
    token_id: uuid.UUID | None = None,
    entity_id: str | uuid.UUID | None = None,
    payload: dict | None = None,
) -> AuditLog:
    """Append an audit row and flush it (the caller owns the commit).

    Attribution is the caller's responsibility and encodes the household-agent
    model: pass ``actor_user_id=None`` for a household-agent pseudo-member token,
    ``token_id=None`` for a web-session write. ``source`` accepts the
    :class:`AuditSource` enum or its string value.
    """
    row = AuditLog(
        household_id=household_id,
        actor_user_id=actor_user_id,
        token_id=token_id,
        source=source.value if isinstance(source, AuditSource) else source,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        payload=payload,
    )
    db.add(row)
    await db.flush()
    return row


async def list_audit_log(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> AuditLogListResponse:
    """Household-scoped audit rows, newest first. Backs the future Activity page."""
    total = (
        await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.household_id == household_id)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.household_id == household_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
