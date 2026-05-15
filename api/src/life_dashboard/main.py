import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.datastructures import MutableHeaders
from starlette.responses import Response as _StarletteResponse
from starlette.types import ASGIApp as _ASGIApp, Receive as _Receive, Scope as _Scope, Send as _Send

from life_dashboard.ai.router import router as ai_router
from life_dashboard.ai.coach_service import run_scheduled_digests
from life_dashboard.auth.router import router as auth_router
from life_dashboard.households.router import router as households_router
from life_dashboard.uploads.router import router as uploads_router
from life_dashboard.domains.calendar_events.router import router as calendar_events_router
from life_dashboard.domains.collections.router import router as collections_router
from life_dashboard.domains.templates.router import router as templates_router, collections_template_router
from life_dashboard.domains.contacts.router import router as contacts_router
from life_dashboard.domains.documents.router import router as documents_router
from life_dashboard.domains.goals.router import router as goals_router
from life_dashboard.domains.projects.router import router as projects_router
from life_dashboard.domains.grocery_lists.router import router as grocery_lists_router
from life_dashboard.domains.habits.router import router as habits_router
from life_dashboard.domains.notes.router import router as notes_router
from life_dashboard.domains.recipes.router import router as recipes_router
from life_dashboard.domains.tags.router import router as tags_router
from life_dashboard.domains.todos.router import router as todos_router
from life_dashboard.domains.notifications.router import router as notifications_router
from life_dashboard.domains.workouts.router import router as workouts_router
from life_dashboard.auth.service import run_bootstrap_if_needed
from life_dashboard.setup.router import router as setup_router
from life_dashboard.core.database import AsyncSessionLocal, create_all_tables, engine, _is_sqlite
from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    logger.info("Starting life_dashboard API  environment=%s", settings.environment)

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection confirmed")
    except Exception as exc:
        # Fail fast — if the DB is unreachable at startup something is wrong
        # with the config (wrong host, bad credentials, port not open).
        logger.critical("Database connection failed: %s", exc)
        raise

    if _is_sqlite():
        # SQLite tier: create schema from ORM metadata on first boot.
        # Subsequent boots are idempotent (create_all skips existing tables).
        await create_all_tables()
        logger.info("SQLite schema initialised (create_all)")

    async with AsyncSessionLocal() as db:
        bootstrapped = await run_bootstrap_if_needed(db)
        if bootstrapped:
            logger.info("Bootstrap complete — initial password has been set")

    # ── AI Coach scheduler ────────────────────────────────────────────────────
    # Generates morning and evening digests for all eligible users.
    # Uses APScheduler's AsyncIOScheduler so jobs run in the same event loop
    # as FastAPI — no thread pool or subprocess needed.
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()

        # Morning digest: fires at 2:00 AM local time each day.
        scheduler.add_job(
            run_scheduled_digests,
            CronTrigger(hour=2, minute=0),
            args=["morning"],
            id="coach_morning",
            replace_existing=True,
            misfire_grace_time=3600,  # If the server was down, catch up within 1 hour.
        )

        # Evening digest: fires at 8:00 PM local time each day.
        scheduler.add_job(
            run_scheduled_digests,
            CronTrigger(hour=20, minute=0),
            args=["evening"],
            id="coach_evening",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        scheduler.start()
        logger.info("AI coach scheduler started (morning=02:00, evening=20:00)")
    except ImportError:
        logger.warning(
            "apscheduler not installed — AI coach background scheduling disabled. "
            "Run: pip install 'apscheduler>=3.10.4'"
        )
        scheduler = None

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("AI coach scheduler stopped")

    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="life_dashboard API",
    version="0.1.0",
    lifespan=lifespan,
    # Swagger/ReDoc are useful in dev but unnecessary surface area in production.
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
)

_cors_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
# When running as a PyInstaller-compiled desktop binary, always permit the
# Tauri WebView origin so the app works even if ALLOWED_ORIGINS wasn't injected.
if getattr(sys, "frozen", False) and "tauri://localhost" not in _cors_origins:
    _cors_origins.append("tauri://localhost")

logger.info("CORS allowed origins: %s", _cors_origins)

# Standard Starlette CORSMiddleware for HTTP/HTTPS origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"tauri://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class _TauriCORSMiddleware:
    """Inject CORS headers for tauri:// scheme origins.

    Starlette's CORSMiddleware has a known limitation with non-HTTP schemes —
    some versions silently drop the Allow-Origin header for tauri://, app://, etc.
    This outermost middleware unconditionally adds the required headers for any
    tauri:// origin, overriding whatever CORSMiddleware decided.

    Safe to run in all environments: no web browser will ever send Origin: tauri://
    so there is no spoofing risk from web clients.
    """

    def __init__(self, app: _ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import Headers
        origin = Headers(scope=scope).get("origin", "")

        if not origin.startswith("tauri://"):
            await self.app(scope, receive, send)
            return

        # Handle CORS preflight before it reaches any other middleware.
        request_headers = Headers(scope=scope)
        if scope["method"] == "OPTIONS" and "access-control-request-method" in request_headers:
            preflight = _StarletteResponse(
                status_code=200,
                headers={
                    "access-control-allow-origin": origin,
                    "access-control-allow-credentials": "true",
                    "access-control-allow-methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
                    "access-control-allow-headers": request_headers.get(
                        "access-control-request-headers", "*"
                    ),
                    "access-control-max-age": "600",
                    "vary": "Origin",
                },
            )
            await preflight(scope, receive, send)
            return

        # Inject headers into every non-preflight response.
        async def _inject(message: dict) -> None:
            if message["type"] == "http.response.start":
                mh = MutableHeaders(scope=message)
                mh["access-control-allow-origin"] = origin
                mh["access-control-allow-credentials"] = "true"
                mh.add_vary_header("Origin")
            await send(message)

        await self.app(scope, receive, _inject)


# Add _TauriCORSMiddleware AFTER CORSMiddleware so it becomes the outermost
# layer (last added = first to handle requests, last to handle responses),
# giving it the final say on Access-Control-Allow-Origin for tauri:// origins.
app.add_middleware(_TauriCORSMiddleware)


app.include_router(setup_router)
app.include_router(ai_router)
app.include_router(auth_router)
app.include_router(households_router)
app.include_router(uploads_router)
app.include_router(calendar_events_router)
app.include_router(collections_router)
app.include_router(templates_router)
app.include_router(collections_template_router)
app.include_router(contacts_router)
app.include_router(documents_router)
app.include_router(goals_router)
app.include_router(projects_router)
app.include_router(grocery_lists_router)
app.include_router(habits_router)
app.include_router(notes_router)
app.include_router(recipes_router)
app.include_router(tags_router)
app.include_router(notifications_router)
app.include_router(todos_router)
app.include_router(workouts_router)


@app.get("/health", tags=["ops"])
async def health():
    """Liveness + DB reachability check. Used by Docker healthcheck and uptime monitors."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception as exc:
        # Return 200 with a degraded status rather than 500 so the container
        # stays up and the caller can decide how to handle it.
        return {"status": "degraded", "database": str(exc)}


@app.get("/debug/cors", tags=["ops"])
async def cors_debug(request: Request):
    """Returns CORS configuration — useful for diagnosing desktop binary issues."""
    return {
        "allowed_origins_setting": settings.allowed_origins,
        "cors_origins_list": _cors_origins,
        "sys_frozen": getattr(sys, "frozen", False),
        "request_origin": request.headers.get("origin"),
    }
