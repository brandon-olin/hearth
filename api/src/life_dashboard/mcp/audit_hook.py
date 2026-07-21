"""
Audit seam for MCP write tools (mcp-002 ⋈ security-008).

mcp-002 (write tools) and security-008 (the ``audit_log`` table + recorder) are
built jointly but land on this shared branch out of order. This module is the
integration seam: every MCP write calls :func:`record_mcp_write`, which forwards
to ``audit.service.record`` as soon as security-008 provides it. Until then the
call is a logged no-op, so the write tools are complete and testable on their
own and gain real auditing the moment the recorder exists — no edit to the tools.

Attribution rules (from the audit design sketch in the track doc):

* ``source`` is always ``"mcp"``.
* ``token_id`` is the acting PAT — every MCP write is token-authenticated.
* ``actor_user_id`` is the owning member for a personal token, but **null for a
  household-agent pseudo-member**: a shared device's writes are attributed to
  the token, not to a person it can't identify.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.mcp.auth import PatIdentity

logger = logging.getLogger(__name__)

#: Membership role of the household-agent pseudo-member (shared devices). Its
#: writes are attributed to the token, never to a person.
_AGENT_ROLE = "agent"

MCP_SOURCE = "mcp"


def _resolve_audit_record():
    """Return ``audit.service.record`` if security-008 has landed it, else None.

    A soft lookup, not a top-level import, so mcp-002 does not hard-depend on
    security-008's merge order. Once ``audit/service.py`` exists this resolves to
    the real recorder and every MCP write is logged with no further change here.
    """
    try:
        from life_dashboard.audit import service as audit_service
    except ImportError:
        return None
    return getattr(audit_service, "record", None)


async def record_mcp_write(
    db: AsyncSession,
    identity: PatIdentity,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    payload: dict[str, Any],
) -> None:
    """Record one MCP write to the audit log (best-effort until security-008).

    A pseudo-member (``role == "agent"``) is attributed with ``actor_user_id =
    None`` and only its ``token_id``; a personal-member token carries both.

    When ``identity`` carries a ``via_proposal_id`` (proposal-001), this same
    call is the **proposed_by** half of an approved proposal's double
    attribution: the write is still attributed to whoever asked for it, tagged
    with the proposal a human said yes to. The approver's half is a separate row
    written by ``proposals.service.approve_proposal`` — two rows, so the two
    actors stay distinguishable rather than collapsing into one.
    """
    record = _resolve_audit_record()
    actor_user_id = None if identity.role == _AGENT_ROLE else identity.user_id

    via_proposal_id = getattr(identity, "via_proposal_id", None)
    if via_proposal_id is not None:
        payload = {**payload, "via_proposal": str(via_proposal_id)}

    if record is None:
        # security-008 not yet on this branch — the call site is in place so
        # auditing lights up on merge. Logged so an interim state is visible.
        logger.debug(
            "MCP write not yet audited (audit.service.record unavailable): "
            "action=%s entity=%s/%s token=%s",
            action, entity_type, entity_id, identity.pat_id,
        )
        return

    await record(
        db,
        household_id=identity.household_id,
        actor_user_id=actor_user_id,
        token_id=identity.pat_id,
        source=MCP_SOURCE,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    # record() flushes but leaves the commit to its caller. The entity write
    # already committed in the tool's service call, so the audit row is the only
    # thing pending here — persist it, or it rolls back when the session closes.
    await db.commit()
