"""Authenticated Server-Sent-Events stream of invalidation events (realtime-001).

Mounted at ``/realtime`` (not ``/events`` — that prefix is the calendar router,
and it maps to the calendar PAT scope). The stream is a web-session surface:
because ``/realtime`` maps to no PAT scope domain, a personal access token is
denied by the auth layer's deny-by-default, so only a logged-in member reaches
it. Each connection is filtered to exactly what that member may see.

Transport note: the browser ``EventSource`` API cannot send an Authorization
header, so the frontend consumes this with a fetch-based reader that does. The
server side is a plain authenticated GET returning ``text/event-stream``.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import HouseholdMembership, User
from life_dashboard.core.database import AsyncSessionLocal
from life_dashboard.events.bus import RESYNC, bus
from life_dashboard.events.scope import can_see

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])

#: How often to emit a heartbeat comment when no events are flowing. Keeps
#: intermediaries from timing out an idle connection and lets us notice a client
#: disconnect promptly (the wait unblocks at least this often).
_HEARTBEAT_SECONDS = 25

#: How often to re-verify the connection's owner is still a member of the
#: household. Auth is checked once at connect (get_current_user); a long-lived
#: stream must not keep delivering events after the member is removed or the
#: household is deleted, so we re-query membership periodically and close the
#: stream if it has gone. Bounds post-removal exposure to this interval.
_MEMBERSHIP_RECHECK_SECONDS = 30


async def _still_a_member(
    db: AsyncSession, household_id, user_id
) -> bool:
    """True if user_id still belongs to household_id — the live membership check
    the SSE loop runs periodically (auth is otherwise only checked at connect)."""
    row = await db.execute(
        select(HouseholdMembership.id).where(
            HouseholdMembership.user_id == user_id,
            HouseholdMembership.household_id == household_id,
        )
    )
    return row.scalar_one_or_none() is not None


async def _event_stream(request: Request, user: User):
    """Yield SSE frames for one connection until the client disconnects or the
    member loses access.

    Forwards only events the member may see (scope filter), translates the
    resync sentinel into a client `resync` event, heartbeats during idle
    periods, and re-checks household membership periodically. Always
    unsubscribes on exit — subscribe and the first yield are inside the try so
    a teardown at any suspension point still runs the finally."""
    household_id = user.household_id  # type: ignore[attr-defined]
    user_id = user.id
    queue = bus.subscribe(household_id)
    loop = asyncio.get_running_loop()
    next_membership_check = loop.time() + _MEMBERSHIP_RECHECK_SECONDS
    try:
        # An initial comment flushes headers immediately so the client's reader
        # resolves the connection as open before the first real event.
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break

            # Periodic re-authorization: stop streaming if the member was
            # removed from the household while connected.
            if loop.time() >= next_membership_check:
                async with AsyncSessionLocal() as db:
                    if not await _still_a_member(db, household_id, user_id):
                        break
                next_membership_check = loop.time() + _MEMBERSHIP_RECHECK_SECONDS

            try:
                item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue

            if item is RESYNC:
                # The client's queue overflowed — tell it to refetch broadly.
                yield "event: resync\ndata: {}\n\n"
                continue

            if not can_see(item, user_id):
                # Scope filter: the member cannot see this entity, so they must
                # not even learn it changed. Silently drop.
                continue

            yield f"event: invalidate\ndata: {json.dumps(item.to_client_dict())}\n\n"
    finally:
        bus.unsubscribe(household_id, queue)


@router.get("/stream")
async def stream(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Open the invalidation stream for the authenticated member.

    Returns a long-lived ``text/event-stream``. The frontend maps each
    ``invalidate`` event ({type, id, action}) to a React Query cache
    invalidation; a ``resync`` event means invalidate everything."""
    return StreamingResponse(
        _event_stream(request, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable proxy buffering (Caddy/nginx/Vercel) so events flush live.
            "X-Accel-Buffering": "no",
        },
    )
