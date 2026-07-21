"""Tier-dependent egress policy for webhook targets (webhook-001).

Two tiers, two entirely different threats:

* **cloud** — the API runs next to other tenants and a metadata service. A
  subscription URL is attacker-controlled input, so anything resolving into
  private, loopback, link-local, or otherwise non-global address space is
  refused. Refused at create time *and again at delivery time*, because a
  hostname that resolved publicly when the subscription was created can be
  re-pointed at ``169.254.169.254`` afterwards (DNS rebinding); a create-time
  check alone is decorative.

* **local / self_hosted** — the whole point of the feature is posting to the
  Home Assistant box on your own LAN. Private targets are ALLOWED here. Only
  obviously-malformed URLs are rejected.

``DEPLOYMENT_TIER`` (core/settings.py) is the switch, so nothing new has to be
configured to get the right behaviour.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)

#: Tiers on which private address space is refused. Everything else is a
#: user-owned machine where LAN targets are the intended use.
_RESTRICTED_TIERS = frozenset({"cloud"})

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class WebhookTargetRejected(ValueError):
    """A subscription URL is not permitted to be called on this tier."""


def egress_is_restricted() -> bool:
    """True when private/loopback targets must be refused (cloud tier)."""
    return settings.deployment_tier in _RESTRICTED_TIERS


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for globally-routable unicast addresses.

    ``is_global`` alone is not enough on its own for IPv6 (it permits some
    reserved ranges), so the disqualifiers are listed explicitly."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def parse_target(url: str) -> tuple[str, int | None]:
    """Validate URL shape and return ``(hostname, port)``.

    Shape rules apply on every tier: a webhook target must be an absolute
    http(s) URL with a host. Raises :class:`WebhookTargetRejected` otherwise.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise WebhookTargetRejected(
            f"URL scheme {parsed.scheme or '(none)'!r} is not supported — use http:// or https://."
        )
    if not parsed.hostname:
        raise WebhookTargetRejected("URL has no host — use an absolute URL like https://example.com/hook.")
    try:
        port = parsed.port
    except ValueError as exc:  # out-of-range port in the URL
        raise WebhookTargetRejected(f"URL has an invalid port: {exc}") from exc
    return parsed.hostname, port


async def _resolve(hostname: str) -> list[str]:
    """Resolve a hostname to every address it currently answers with."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


async def assert_target_allowed(url: str) -> None:
    """Refuse ``url`` if this tier forbids where it points. No-op if allowed.

    Called at subscription create time AND before every delivery attempt. On a
    restricted tier the hostname is re-resolved each time, so a rebound DNS
    record is caught on the next attempt rather than never.
    """
    hostname, _ = parse_target(url)

    if not egress_is_restricted():
        # Self-hosted / local: LAN and loopback targets are the use case.
        return

    # A bare IP literal never needs resolving — check it directly.
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(literal):
            raise WebhookTargetRejected(
                f"{hostname} is a private, loopback, or link-local address. On the cloud "
                "tier a webhook must target a publicly-routable host."
            )
        return

    try:
        addresses = await _resolve(hostname)
    except socket.gaierror as exc:
        raise WebhookTargetRejected(f"Could not resolve {hostname}: {exc}") from exc

    if not addresses:
        raise WebhookTargetRejected(f"{hostname} resolved to no addresses.")

    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if not _ip_is_public(ip):
            raise WebhookTargetRejected(
                f"{hostname} resolves to {raw}, which is private, loopback, or link-local. "
                "On the cloud tier a webhook must target a publicly-routable host."
            )
