"""Per-token rate limiting for PAT-authenticated requests (security-007).

Cloud-tier concern. On local and self-hosted installs the caller is a trusted
household on a private network, so no per-token throttle applies — the existing
per-IP limits on the public auth endpoints are enough. On the cloud tier a PAT
(possibly minted through OAuth account linking for a third-party platform) is an
internet-facing credential, so each token gets its own request budget: a noisy
or compromised token is contained without affecting other tokens or members.

Fixed-window counter in process memory, keyed by token id. This mirrors the
in-memory strategy of core.rate_limit (slowapi) and carries the same caveat:
the window is per-process, so a multi-worker cloud deployment would let a token
burst up to ``limit × worker_count`` before any single worker throttles it. That
is an acceptable coarse ceiling for abuse containment; a Redis-backed shared
counter is the swap-in if precise global limits are ever needed, exactly as
core.rate_limit documents for its own storage.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

#: Window length. Requests are counted per token per this many seconds.
_WINDOW_SECONDS = 60

# token_id -> (window_start_epoch, count). Guarded by _lock because the counter
# is a plain dict and, while the event loop is single-threaded, the app may run
# under a threaded worker; the operations are trivial so contention is nil.
#
# The dict is swept of stale entries whenever the window advances (see
# check_rate_limit) so it stays bounded by the number of *distinct tokens active
# within a single window* — a token that stops calling is dropped at the next
# sweep rather than lingering forever. This matters because OAuth mints a fresh
# PAT per completed grant, so without eviction the table would grow without
# bound on a long-lived cloud process.
_counters: dict[uuid.UUID, tuple[float, int]] = {}
#: The window a sweep last ran for; a sweep runs at most once per window.
_last_swept_window: float = -1.0
_lock = threading.Lock()


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def check_rate_limit(token_id: uuid.UUID, limit: int, now: float | None = None) -> bool:
    """Record one request for ``token_id`` and return True if it is within the
    per-window ``limit``, False if the token has exceeded it.

    A non-positive ``limit`` disables throttling (returns True) — the setting's
    escape hatch. ``now`` is injectable so tests need not sleep out a window.
    """
    if limit <= 0:
        return True

    ts = _now_epoch() if now is None else now
    window_start = ts - (ts % _WINDOW_SECONDS)

    global _last_swept_window
    with _lock:
        # When the window advances, drop every counter left in a prior window —
        # those tokens are idle and their entries would otherwise leak.
        if window_start != _last_swept_window:
            stale = [tid for tid, (start, _) in _counters.items() if start < window_start]
            for tid in stale:
                del _counters[tid]
            _last_swept_window = window_start

        start, count = _counters.get(token_id, (window_start, 0))
        if start != window_start:
            # A new window opened — reset the count for this token.
            start, count = window_start, 0
        count += 1
        _counters[token_id] = (start, count)
        return count <= limit


def reset() -> None:
    """Clear all counters. For tests and process-local teardown only."""
    global _last_swept_window
    with _lock:
        _counters.clear()
        _last_swept_window = -1.0
