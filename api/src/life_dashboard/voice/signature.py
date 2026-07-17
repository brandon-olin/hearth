"""Alexa request verification (voice-002).

Amazon signs every request a certified skill receives; a skill whose endpoint is
a public HTTPS URL (rather than a Lambda) must verify that signature itself, or
anyone who learns the URL could POST forged intents. Three independent checks,
each defeating a different forgery:

* **applicationId** — the request names *this* skill. Cheap, no network; always
  enforced once ``alexa_skill_id`` is configured. Meaningful only alongside the
  signature (an attacker could otherwise just echo the id), but free to add.
* **timestamp freshness** — the request is at most 150 s old, so a captured
  request can't be replayed later.
* **request signature** — the body was signed by Amazon's private key, proven
  against the certificate chain named in ``SignatureCertChainUrl``.

The signature check needs outbound HTTPS to Amazon's S3 cert host, so it is
gated by ``settings.alexa_verify_signature`` (off for local/self-hosted, on for
the internet-facing cloud tier). applicationId and timestamp are pure and always
available; the router runs whichever are configured.

Note: this validates the leaf certificate (host, validity window, Amazon SAN)
and the signature over the body. Full X.509 path validation to Amazon's root is
a further hardening step; combined with the applicationId check and the fact
that every intent still requires a valid account-linked PAT, the residual risk
is small and the surface is off by default.
"""
from __future__ import annotations

import base64
import posixpath
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

#: DNS name every valid Alexa signing certificate carries in its SAN.
_ALEXA_SAN = "echo-api.amazon.com"

#: Max age of a request Amazon considers valid; older requests are replays.
_TIMESTAMP_TOLERANCE_SECONDS = 150

#: Fetched signing keys cached by URL as (public_key, not_valid_after) so a
#: per-request S3 round-trip isn't added to every intent. The expiry is stored
#: alongside the key and re-checked on every cache hit — a cached cert is dropped
#: and re-fetched (re-validating window + SAN) once it passes its not_valid_after,
#: so a rotated or expired cert at the same URL is never trusted past its life.
_CERT_CACHE: dict[str, tuple[rsa.RSAPublicKey, datetime]] = {}


class AlexaVerificationError(Exception):
    """A request failed a security check — forged, stale, or from another skill.
    The router turns this into a non-200 so Amazon (and any forger) gets a plain
    rejection, never a spoken response."""


def check_application_id(request_app_id: str | None, expected: str | None) -> None:
    """Reject a request that does not name the configured skill. A no-op when no
    skill id is configured (local dev), since there is nothing to compare to."""
    if not expected:
        return
    if request_app_id != expected:
        raise AlexaVerificationError("applicationId does not match this skill.")


def check_timestamp(timestamp: datetime | None, *, now: datetime | None = None) -> None:
    """Reject a request whose timestamp is missing or outside the tolerance
    window (in either direction — future-dated requests are equally suspect)."""
    if timestamp is None:
        raise AlexaVerificationError("Request has no timestamp.")
    now = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    skew = abs((now - timestamp).total_seconds())
    if skew > _TIMESTAMP_TOLERANCE_SECONDS:
        raise AlexaVerificationError("Request timestamp is outside the allowed window.")


def _validate_cert_url(url: str) -> None:
    """Validate SignatureCertChainUrl per Amazon's rules before fetching it, so a
    forged header can't point us at an attacker-controlled host (SSRF)."""
    if not url:
        raise AlexaVerificationError("Missing SignatureCertChainUrl.")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise AlexaVerificationError("Cert chain URL must be https.")
    if (parsed.hostname or "").lower() != "s3.amazonaws.com":
        raise AlexaVerificationError("Cert chain URL host is not s3.amazonaws.com.")
    if parsed.port not in (None, 443):
        raise AlexaVerificationError("Cert chain URL port must be 443.")
    # normpath collapses ".." tricks before the prefix check.
    if not posixpath.normpath(parsed.path).startswith("/echo.api/"):
        raise AlexaVerificationError("Cert chain URL path must be under /echo.api/.")


async def _load_signing_key(cert_url: str) -> rsa.RSAPublicKey:
    """Fetch and validate the signing certificate chain, returning the leaf's
    public key. Cached by URL, but the cache is honored only while the cert is
    still within its validity window — an expired entry is dropped and the cert
    re-fetched and re-validated, never trusted past its not_valid_after."""
    now = datetime.now(timezone.utc)
    cached = _CERT_CACHE.get(cert_url)
    if cached is not None:
        public_key, not_valid_after = cached
        if now <= not_valid_after:
            return public_key
        _CERT_CACHE.pop(cert_url, None)  # expired — force a fresh fetch + re-validate

    _validate_cert_url(cert_url)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(cert_url)
        resp.raise_for_status()

    certs = x509.load_pem_x509_certificates(resp.content)
    if not certs:
        raise AlexaVerificationError("Cert chain is empty.")
    leaf = certs[0]

    if not (leaf.not_valid_before_utc <= now <= leaf.not_valid_after_utc):
        raise AlexaVerificationError("Signing certificate is expired or not yet valid.")

    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    if _ALEXA_SAN not in san.get_values_for_type(x509.DNSName):
        raise AlexaVerificationError("Signing certificate is not an Alexa certificate.")

    public_key = leaf.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise AlexaVerificationError("Signing certificate is not RSA.")

    _CERT_CACHE[cert_url] = (public_key, leaf.not_valid_after_utc)
    return public_key


async def verify_signature(body: bytes, cert_url: str, signature_b64: str) -> None:
    """Verify the request body was signed by Amazon (RSA-SHA1 over the raw body).
    Raises :class:`AlexaVerificationError` on any failure."""
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise AlexaVerificationError("Signature is not valid base64.") from exc

    public_key = await _load_signing_key(cert_url)
    try:
        public_key.verify(signature, body, padding.PKCS1v15(), hashes.SHA1())
    except InvalidSignature as exc:
        raise AlexaVerificationError("Request signature does not match the body.") from exc
