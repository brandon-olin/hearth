"""
Desktop entry point — compiled by PyInstaller into the life_dashboard_api binary.

This thin wrapper launches Uvicorn with the FastAPI app.  We keep it separate
from main.py so that PyInstaller has a concrete __main__ target and so that the
desktop binary can accept a --port flag without touching the server code.

Usage (development):
    python -m life_dashboard.desktop_entry

Usage (compiled binary):
    ./life_dashboard_api [--host HOST] [--port PORT]
"""

import argparse
import os
import sys

# ── Desktop-specific env defaults ────────────────────────────────────────────
# These must be set BEFORE importing life_dashboard.main because pydantic-settings
# reads os.environ when the Settings() singleton is first instantiated.
#
# Tauri's sidecar launcher also injects these, but setting them here as fallbacks
# guarantees correct values even when the binary is run directly for debugging.

# Always allow the Tauri WebView origin in the desktop binary.
_existing_origins = os.environ.get("ALLOWED_ORIGINS", "")
_tauri_origin = "tauri://localhost"
if _tauri_origin not in _existing_origins:
    os.environ["ALLOWED_ORIGINS"] = (
        f"{_tauri_origin},{_existing_origins}" if _existing_origins else _tauri_origin
    )

# Default to a local SQLite DB in the user's home dir if no DATABASE_URL set.
if not os.environ.get("DATABASE_URL"):
    _default_db = os.path.expanduser("~/.life_dashboard/life_dashboard.db")
    os.makedirs(os.path.dirname(_default_db), exist_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_default_db}"

# Generate a stable JWT secret if none provided.
if not os.environ.get("JWT_SECRET_KEY"):
    _secret_file = os.path.expanduser("~/.life_dashboard/jwt_secret.key")
    if os.path.exists(_secret_file):
        os.environ["JWT_SECRET_KEY"] = open(_secret_file).read().strip()
    else:
        import secrets
        _secret = secrets.token_hex(32)
        os.makedirs(os.path.dirname(_secret_file), exist_ok=True)
        with open(_secret_file, "w") as _f:
            _f.write(_secret)
        os.environ["JWT_SECRET_KEY"] = _secret

# ─────────────────────────────────────────────────────────────────────────────

import uvicorn  # noqa: E402

# Import the app object directly — uvicorn's string-based import path does not
# work inside a PyInstaller-frozen binary because the module loader can't
# resolve dotted names in the frozen module store.  Passing the object avoids
# the dynamic import entirely.
from life_dashboard.main import app as _app  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="life_dashboard_api",
        description="Hearth FastAPI server",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1 — loopback only for desktop)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=1338,
        help="Bind port (default: 1338)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Uvicorn log level (default: info)",
    )
    # Accept (and ignore) unknown flags so Tauri sidecar passthrough doesn't error.
    return parser.parse_known_args(sys.argv[1:])[0]


if __name__ == "__main__":
    args = _parse_args()

    uvicorn.run(
        _app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        # Reload is never used in the compiled binary; disable it explicitly so
        # PyInstaller-frozen code doesn't attempt to watch source files.
        reload=False,
        # Use asyncio event loop — uvloop is optional and may not be bundled.
        loop="asyncio",
    )
