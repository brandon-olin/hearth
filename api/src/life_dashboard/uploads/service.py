"""
Upload service — shared helpers for programmatic file storage.

The router handles user-initiated uploads; this module is for server-side
ingest (e.g. downloading a remote cover image at recipe-import time).
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import aiofiles
import httpx

from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)

# Content-type → file extension
_EXT_MAP: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
}

_ALLOWED_TYPES = set(_EXT_MAP)
_MAX_BYTES = 20 * 1024 * 1024  # 20 MB ceiling for remote images


def _upload_dir() -> Path:
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _is_external_url(url: str | None) -> bool:
    return bool(url and (url.startswith("http://") or url.startswith("https://")))


async def download_remote_image(url: str) -> str | None:
    """
    Fetch *url*, save the image to the upload directory, and return the
    local ``/uploads/{filename}`` path.

    Returns ``None`` (and logs a warning) instead of raising so callers
    can fall back to storing the original URL rather than aborting the
    whole operation.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; life-dashboard/1.0)"
            ),
            "Accept": "image/*,*/*;q=0.8",
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()

        # Sniff common image magic bytes if content-type is unhelpful
        if content_type not in _ALLOWED_TYPES:
            data = response.content
            if data[:3] == b"\xff\xd8\xff":
                content_type = "image/jpeg"
            elif data[:8] == b"\x89PNG\r\n\x1a\n":
                content_type = "image/png"
            elif data[:4] in (b"RIFF", b"WEBP"):
                content_type = "image/webp"
            elif data[:6] in (b"GIF87a", b"GIF89a"):
                content_type = "image/gif"
            else:
                logger.warning("download_remote_image: unrecognised content-type %r for %s", content_type, url)
                return None
        else:
            data = response.content

        if len(data) > _MAX_BYTES:
            logger.warning("download_remote_image: image too large (%d bytes) from %s", len(data), url)
            return None

        ext = _EXT_MAP.get(content_type, ".jpg")
        filename = f"{uuid.uuid4()}{ext}"
        dest = _upload_dir() / filename

        async with aiofiles.open(dest, "wb") as f:
            await f.write(data)

        logger.debug("download_remote_image: saved %s → %s", url, filename)
        return f"/uploads/{filename}"

    except Exception as exc:
        logger.warning("download_remote_image: failed to fetch %s — %s", url, exc)
        return None
