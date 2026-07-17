"""The ``@audited`` decorator for MCP write tools (security-008).

Wrapping a write tool with :func:`audited` guarantees an ``audit_log`` row is
recorded for every successful call, attributed to the calling token — so a tool
author cannot forget to audit. mcp-002's write tools apply it::

    @mcp_server.tool()
    @audited(action="create", entity_type="todo")
    async def add_todo(ctx: Context, title: str, ...) -> dict:
        ...
        return created.model_dump(mode="json")   # dict with an "id"

Design:

* **Records after the tool returns, in its own session.** The wrapped tool owns
  its write and commits it; the audit row is appended afterward. A tool that
  raises is never recorded (the write did not happen).
* **Attribution is re-resolved from the request**, not trusted from the tool's
  return — the decorator calls :func:`resolve_pat` (imported lazily so the audit
  package carries no import-time dependency on the mcp package). ``token_id`` is
  always the calling PAT; ``actor_user_id`` is the token's owning member, except
  for a **household-agent pseudo-member** token (a shared device), where it is
  ``None`` — the row is attributed to the token alone. See :data:`HOUSEHOLD_AGENT_ROLE`.
* **Never masks the tool.** If recording fails, the tool's result is still
  returned and the failure is logged — an audit outage must not break a write
  that already committed.
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

from life_dashboard.audit.schemas import AuditSource
from life_dashboard.audit.service import record

logger = logging.getLogger(__name__)

#: The membership role of the household-agent pseudo-member (mcp-002). A write
#: made by a token whose owner has this role is attributed to the token alone
#: (actor_user_id NULL). This is the contract between security-008 and mcp-002:
#: mcp-002 must create the pseudo-member with this role value.
HOUSEHOLD_AGENT_ROLE = "agent"

#: Whitelisted keys copied from a tool's result into the audit payload summary.
#: A whitelist (never a dump of the whole row) keeps sensitive fields out of the
#: log by default; a tool can override with an explicit ``summary`` extractor.
_SAFE_SUMMARY_KEYS = frozenset(
    {"id", "title", "name", "status", "scheduled_date", "starts_at", "due_date", "completed"}
)


def _is_household_agent(identity) -> bool:
    """True if the caller is the household-agent pseudo-member — its writes are
    attributed to the token, not a person (actor_user_id NULL)."""
    return getattr(identity, "role", None) == HOUSEHOLD_AGENT_ROLE


def resolve_actor_user_id(identity) -> Any:
    """The ``actor_user_id`` to attribute a write by ``identity`` to: the owning
    member, or ``None`` for a household-agent pseudo-member token."""
    return None if _is_household_agent(identity) else identity.user_id


def _default_entity_id(result: Any) -> str | None:
    if isinstance(result, dict) and result.get("id") is not None:
        return str(result["id"])
    return None


def _default_summary(result: Any) -> dict | None:
    if not isinstance(result, dict):
        return None
    return {k: result[k] for k in _SAFE_SUMMARY_KEYS if k in result} or None


def audited(
    *,
    action: str,
    entity_type: str,
    source: AuditSource | str = AuditSource.mcp,
    entity_id: Callable[[Any], str | None] | None = None,
    summary: Callable[[Any], dict | None] | None = None,
):
    """Wrap an MCP tool ``async def fn(ctx, ...) -> dict`` so every successful
    call records an attributed ``audit_log`` row.

    ``entity_id`` / ``summary`` default to extracting the ``"id"`` and a
    whitelisted digest from the tool's returned dict; pass callables to override.
    """
    extract_id = entity_id or _default_entity_id
    build_summary = summary or _default_summary

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(ctx, *args, **kwargs):
            result = await fn(ctx, *args, **kwargs)
            try:
                # Lazy import keeps `import life_dashboard.audit` free of any
                # dependency on the (concurrently built) mcp package.
                from life_dashboard.core.database import AsyncSessionLocal
                from life_dashboard.mcp.auth import resolve_pat

                async with AsyncSessionLocal() as db:
                    _, identity = await resolve_pat(db, ctx)
                    await record(
                        db,
                        household_id=identity.household_id,
                        actor_user_id=resolve_actor_user_id(identity),
                        token_id=identity.pat_id,
                        source=source,
                        action=action,
                        entity_type=entity_type,
                        entity_id=extract_id(result),
                        payload=build_summary(result),
                    )
                    await db.commit()
            except Exception:
                # The write already committed inside the tool; a failed audit
                # must not turn a successful write into an error for the agent.
                logger.exception(
                    "audit_log record failed for action=%s entity_type=%s", action, entity_type
                )
            return result

        return wrapper

    return decorator
