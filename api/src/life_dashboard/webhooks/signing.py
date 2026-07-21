"""Payload serialisation and HMAC signing for outbound deliveries (webhook-001).

The signature is Stripe-shaped and timestamped:

    X-Hearth-Signature: t=<unix seconds>, v1=<hex HMAC-SHA256>

where the signed message is ``f"{t}.{body}"`` and ``body`` is the exact bytes
sent. A receiver recomputes the HMAC with its subscription secret and compares
in constant time; because ``t`` is inside the signed message, a captured body
cannot be replayed under a fresh timestamp, and the receiver rejects anything
whose ``t`` is outside its tolerance window (5 minutes is the documented
default — see docs/webhooks.md).

Serialisation is canonical (sorted keys, no incidental whitespace) so a retry of
the same delivery produces byte-identical bytes, and so a receiver that re-reads
the raw body gets exactly what was signed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

#: Header carrying the timestamp + signature pair.
SIGNATURE_HEADER = "X-Hearth-Signature"
#: Header carrying the delivery id — the receiver's dedupe key across retries.
DELIVERY_HEADER = "X-Hearth-Delivery"
#: Header carrying the event name, so a receiver can route without parsing JSON.
EVENT_HEADER = "X-Hearth-Event"

#: Signature scheme version. A future scheme is added as ``v2=`` alongside ``v1=``
#: so receivers can migrate without a flag day.
SIGNATURE_VERSION = "v1"


def canonical_body(payload: dict[str, Any]) -> bytes:
    """Serialise a payload to the exact bytes that will be signed and sent."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def signature_message(timestamp: int, body: bytes) -> bytes:
    """The message the HMAC covers: ``<t>.<body>``."""
    return f"{timestamp}.".encode() + body


def compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    """Hex HMAC-SHA256 of ``<t>.<body>`` under the subscription secret."""
    return hmac.new(
        secret.encode("utf-8"), signature_message(timestamp, body), hashlib.sha256
    ).hexdigest()


def signature_header(secret: str, timestamp: int, body: bytes) -> str:
    """The full ``X-Hearth-Signature`` value for one attempt."""
    return f"t={timestamp}, {SIGNATURE_VERSION}={compute_signature(secret, timestamp, body)}"


def verify_signature(
    secret: str,
    header: str,
    body: bytes,
    *,
    now: int,
    tolerance_seconds: int = 300,
) -> bool:
    """Receiver-side verification — the reference implementation the docs describe.

    Lives here so the recipe published to users is the code this build actually
    tests against, rather than prose that can drift. Returns False for a malformed
    header, a timestamp outside ``tolerance_seconds`` (replay), or a signature
    that does not match the body (tamper).
    """
    parts = dict(
        piece.strip().split("=", 1)
        for piece in header.split(",")
        if "=" in piece
    )
    raw_t = parts.get("t")
    provided = parts.get(SIGNATURE_VERSION)
    if not raw_t or not provided:
        return False
    try:
        timestamp = int(raw_t)
    except ValueError:
        return False
    if abs(now - timestamp) > tolerance_seconds:
        return False
    return hmac.compare_digest(provided, compute_signature(secret, timestamp, body))
