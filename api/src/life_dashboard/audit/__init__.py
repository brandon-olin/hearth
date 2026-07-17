"""Audit log package (security-008) — an attributed record of writes.

Public surface:

* :func:`audited` — decorator for MCP write tools (mcp-002 applies it).
* :func:`record` — the write primitive; web routes can adopt it later.
* :func:`list_audit_log` — household-scoped query, newest first.
* :class:`AuditLog`, :class:`AuditSource`, response schemas.

Importing this package registers the ``AuditLog`` table on ``Base.metadata`` but
pulls in **no** mcp code — the decorator's dependency on ``mcp.auth`` is resolved
lazily at call time, so the (concurrently built) mcp package need not exist to
import ``life_dashboard.audit``.
"""
from life_dashboard.audit.decorator import HOUSEHOLD_AGENT_ROLE, audited, resolve_actor_user_id
from life_dashboard.audit.models import AuditLog
from life_dashboard.audit.schemas import (
    AuditLogListResponse,
    AuditLogResponse,
    AuditSource,
)
from life_dashboard.audit.service import list_audit_log, record

__all__ = [
    "AuditLog",
    "AuditLogListResponse",
    "AuditLogResponse",
    "AuditSource",
    "HOUSEHOLD_AGENT_ROLE",
    "audited",
    "list_audit_log",
    "record",
    "resolve_actor_user_id",
]
