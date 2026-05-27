"""
Image upload endpoint.

Files are stored on the local filesystem at settings.upload_dir using a flat
UUID-based filename (e.g. /data/uploads/3fa85f64-...jpg). The upload_dir is
mounted as a Docker volume so files survive container rebuilds.

The GET /uploads/{filename} endpoint is intentionally unauthenticated: the
UUID filename (128-bit random) is unguessable, and the app runs behind
Tailscale which provides network-level access control. This allows <img> tags
in the BlockNote editor to load without needing JS-injected Authorization
headers.
"""

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.settings import settings

router = APIRouter(prefix="/uploads", tags=["uploads"])

# ── Constants ─────────────────────────────────────────────────────────────────

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
}

EXTENSION_MAP = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_upload_dir() -> Path:
    """Return the upload directory path, creating it if needed."""
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """
    Upload an image file. Returns the URL path to use in the editor.

    Accepts: image/jpeg, image/png, image/gif, image/webp
    Max size: settings.max_upload_size_mb (default 10 MB)
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            415,
            detail=f"Unsupported media type: {file.content_type!r}. "
                   "Only JPEG, PNG, GIF, and WebP images are accepted.",
        )

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    content = await file.read()

    if len(content) > max_bytes:
        raise HTTPException(
            413,
            detail=f"File size {len(content) // 1024} KB exceeds the "
                   f"{settings.max_upload_size_mb} MB limit.",
        )

    ext = EXTENSION_MAP.get(file.content_type or "", ".jpg")
    filename = f"{uuid.uuid4()}{ext}"
    dest = _get_upload_dir() / filename

    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    return {"url": f"/uploads/{filename}"}


@router.get("/{filename}")
async def serve_upload(filename: str) -> FileResponse:
    """
    Serve a previously uploaded image file.

    No authentication required — files are identified by unguessable UUID
    filenames and the app is expected to run behind Tailscale or equivalent.
    """
    # Guard against path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, detail="Invalid filename.")

    path = _get_upload_dir() / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404, detail="File not found.")

    return FileResponse(path)
