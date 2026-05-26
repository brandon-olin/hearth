"""
Rate limiting for public endpoints.

Uses slowapi (wraps the `limits` library) with in-memory storage.
In-memory storage is appropriate for the local and self-hosted tiers
(single process). For the cloud tier with multiple workers, swap
MemoryStorage for RedisStorage by updating the Limiter constructor.

Key function
------------
Uses X-Forwarded-For when present (set by Caddy in self-hosted and by
Vercel in cloud). Falls back to the direct client IP for local dev.
Only the first (leftmost) address in X-Forwarded-For is trusted — this
is the original client IP as set by the outermost proxy.

Limits applied
--------------
/auth/login    — 5 per minute per IP   (brute-force protection)
/auth/register — 3 per hour per IP     (spam account prevention)

These are intentionally conservative for a household app. A real user
would never hit them under normal use.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _real_ip(request: Request) -> str:
    """Return the originating client IP, respecting reverse-proxy headers."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can be a comma-separated list; the first entry is
        # the original client. Subsequent entries are intermediate proxies.
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    # Direct connection (local dev, no proxy in front)
    return get_remote_address(request)


limiter = Limiter(key_func=_real_ip)
