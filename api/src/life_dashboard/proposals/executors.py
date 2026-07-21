"""Tool name → the function that performs its write (proposal-001).

Approving a proposal must run **the same code the direct write runs**, not a
reimplementation of it — otherwise an approved write could drift from the
tool it was proposed through, and the audit trail would describe an action that
never quite happened.

Each MCP write tool therefore splits into two halves:

* a thin tool that authorizes, and either proposes or delegates, and
* a ``_perform_*`` function holding the entire write, registered here.

The direct path and the approval path both call the registered function. The
registry lives in this module rather than in ``mcp/server.py`` so the proposals
service can reach it without importing the MCP server at module scope (the MCP
server already imports the proposals service — the other direction would cycle).

Registration is a side effect of importing ``mcp.server``, so
:func:`get_executor` imports it lazily on a miss.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

#: ``async def executor(db, identity, **args) -> dict``. ``identity`` is a
#: PatIdentity describing the PROPOSER (not the approver): the entity is created
#: on the proposer's behalf, and its audit row is the proposed_by fact.
Executor = Callable[..., Awaitable[dict[str, Any]]]

_REGISTRY: dict[str, Executor] = {}


def register_executor(tool: str):
    """Register the function that performs *tool*'s write, keyed by tool name.

    The key is stored in ``proposals.tool``, so renaming a tool without a data
    migration would orphan its pending proposals — approval fails closed with
    "no executor", which is the correct outcome for a call we can no longer
    faithfully replay.
    """

    def decorator(fn: Executor) -> Executor:
        _REGISTRY[tool] = fn
        return fn

    return decorator


def get_executor(tool: str) -> Executor | None:
    """The executor for *tool*, or None if nothing can replay it."""
    if tool not in _REGISTRY:
        # Registration happens as an import side effect of the MCP server.
        # Imported lazily and tolerantly: a deployment without the MCP surface
        # should fail this one approval, not fail to boot.
        try:
            import life_dashboard.mcp.server  # noqa: F401
        except ImportError:  # pragma: no cover — MCP is always installed today
            return None
    return _REGISTRY.get(tool)


async def run_executor(
    db: AsyncSession, tool: str, identity, args: dict[str, Any]
) -> dict[str, Any] | None:
    """Replay *tool* with *args* as *identity*, or None if it has no executor."""
    executor = get_executor(tool)
    if executor is None:
        return None
    return await executor(db, identity, **args)
