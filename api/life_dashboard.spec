# PyInstaller spec — builds the FastAPI app into a single binary for bundling
# inside the Tauri desktop app.
#
# Usage:
#   cd api
#   source .venv/bin/activate
#   pip install pyinstaller
#   pyinstaller life_dashboard.spec
#
# Output: dist/life_dashboard_api  (macOS/Linux)
#         dist/life_dashboard_api.exe  (Windows)
#
# The binary is placed in desktop/src-tauri/binaries/ by the build script
# with Tauri's required naming convention:
#   life_dashboard_api-x86_64-apple-darwin        (macOS Intel)
#   life_dashboard_api-aarch64-apple-darwin       (macOS Apple Silicon)
#   life_dashboard_api-x86_64-pc-windows-msvc.exe (Windows)
#   life_dashboard_api-x86_64-unknown-linux-gnu   (Linux)

import sys
from pathlib import Path

block_cipher = None

# Entry point — runs Uvicorn with the FastAPI app.
# We use a thin wrapper script rather than importing uvicorn directly because
# PyInstaller needs a concrete __main__ entry point.
entry = Path("src/life_dashboard/desktop_entry.py")

a = Analysis(
    [str(entry)],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[
        # SQLAlchemy dialects
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.postgresql",
        # Async drivers
        "aiosqlite",
        "asyncpg",
        # FastAPI / Uvicorn internals
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.loops.uvloop",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # Pydantic
        "pydantic",
        "pydantic_settings",
        "pydantic.deprecated.class_validators",
        # Auth
        "argon2",
        "argon2._utils",
        "jose",
        "jose.jwt",
        # All domain modules (ensure they're included even if not directly imported)
        "life_dashboard.auth.models",
        "life_dashboard.ai.models",
        "life_dashboard.domains.calendar_events.models",
        "life_dashboard.domains.collections.models",
        "life_dashboard.domains.contacts.models",
        "life_dashboard.domains.documents.models",
        "life_dashboard.domains.goals.models",
        "life_dashboard.domains.grocery_lists.models",
        "life_dashboard.domains.habits.models",
        "life_dashboard.domains.notes.models",
        "life_dashboard.domains.projects.models",
        "life_dashboard.domains.recipes.models",
        "life_dashboard.domains.tags.models",
        "life_dashboard.domains.todos.models",
        "life_dashboard.domains.workouts.models",
        # Anthropic SDK
        "anthropic",
        "httpx",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy unused packages
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "cv2",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="life_dashboard_api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=True keeps stdout/stderr visible for debugging; set to False
    # for a silent background process in production.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
