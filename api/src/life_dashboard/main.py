import logging
import logging.handlers
import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.datastructures import MutableHeaders
from starlette.responses import Response as _StarletteResponse
from starlette.types import ASGIApp as _ASGIApp, Receive as _Receive, Scope as _Scope, Send as _Send

from life_dashboard.ai.router import router as ai_router
from life_dashboard.ai.coach_service import run_scheduled_digests
from life_dashboard.domains.budget.service import sync_all_teller_accounts_globally
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
from life_dashboard.domains.budget.router import router as budget_router
from life_dashboard.auth.service import run_bootstrap_if_needed
from life_dashboard.setup.router import router as setup_router
from life_dashboard.core.database import AsyncSessionLocal, create_all_tables, engine, _is_sqlite
from life_dashboard.core.rate_limit import limiter
from life_dashboard.core.settings import settings

logger = logging.getLogger(__name__)


def _setup_file_logging() -> None:
    """Write all WARNING+ logs (plus full tracebacks) to api/api.log.
    The file rotates at 2 MB, keeping 3 backups — readable by the coding agent."""
    log_path = Path(__file__).resolve().parents[3] / "api.log"
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)
    # Also capture uvicorn access/error logs
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(name).addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    _setup_file_logging()

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

        # budget-010 data migration: rename old enum values personal→private, household→shared.
        # Safe to run on every boot — the WHERE clause makes it idempotent.
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE budget_categories SET default_scope = 'private' WHERE default_scope = 'personal'"
                ))
                await conn.execute(text(
                    "UPDATE budget_categories SET default_scope = 'shared' WHERE default_scope = 'household'"
                ))
                await conn.execute(text(
                    "UPDATE budget_transactions SET scope = 'private' WHERE scope = 'personal'"
                ))
                await conn.execute(text(
                    "UPDATE budget_transactions SET scope = 'shared' WHERE scope = 'household'"
                ))
            logger.info("budget-010 enum migration complete (personal→private, household→shared)")
        except Exception as exc:
            logger.warning("budget-010 enum migration failed (non-fatal): %s", exc)

        # budget-profiles seed: create Personal + Household profiles for any household that
        # has budget data (categories/groups/accounts) but no profiles yet.
        # MUST run before budget-009 (which assigns profiles to orphaned rows).
        # Idempotent — only targets households where budget_profiles is empty.
        try:
            import uuid as _uuid_mod
            async with engine.begin() as conn:
                hh_rows = await conn.execute(text(
                    "SELECT h.id, hm.user_id FROM households h "
                    "JOIN household_memberships hm ON hm.household_id = h.id "
                    "WHERE NOT EXISTS (SELECT 1 FROM budget_profiles bp WHERE bp.household_id = h.id) "
                    "GROUP BY h.id"
                ))
                for hh_id, user_id in hh_rows.fetchall():
                    for idx, (prof_name, prof_style) in enumerate([
                        ("Personal",  "zero_based"),
                        ("Household", "zero_based"),
                    ]):
                        pid = str(_uuid_mod.uuid4())
                        await conn.execute(text(
                            "INSERT INTO budget_profiles "
                            "(id, household_id, name, budgeting_style, currency, sort_order, created_at, updated_at) "
                            "VALUES (:id, :hh, :name, :style, 'USD', :sort, datetime('now'), datetime('now'))"
                        ), {"id": pid, "hh": hh_id, "name": prof_name, "style": prof_style, "sort": idx + 1})
                        # Add user as owner member
                        mid = str(_uuid_mod.uuid4())
                        await conn.execute(text(
                            "INSERT INTO budget_profile_members "
                            "(id, profile_id, user_id, role, created_at, updated_at) "
                            "VALUES (:id, :pid, :uid, 'owner', datetime('now'), datetime('now'))"
                        ), {"id": mid, "pid": pid, "uid": user_id})
                        logger.info("Seeded budget profile '%s' for household %s", prof_name, hh_id)
            logger.info("Budget profiles seeding complete")
        except Exception as exc:
            logger.warning("Budget profiles seeding failed (non-fatal): %s", exc)

        # budget-009 data migration: re-assign orphaned categories/groups/accounts
        # (profile_id IS NULL) to the appropriate profile. Rows with null profile_id
        # cause Pydantic validation errors. Safe to run on every boot — idempotent
        # via the WHERE clause. Runs after profile seeding above so profiles exist.
        try:
            async with engine.begin() as conn:
                # Categories → Personal profile
                await conn.execute(text("""
                    UPDATE budget_categories
                    SET profile_id = (
                        SELECT id FROM budget_profiles
                        WHERE budget_profiles.household_id = budget_categories.household_id
                          AND budget_profiles.name = 'Personal'
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL
                """))
                # Groups → Household profile (preferred) else Personal
                await conn.execute(text("""
                    UPDATE budget_category_groups
                    SET profile_id = (
                        SELECT id FROM budget_profiles
                        WHERE budget_profiles.household_id = budget_category_groups.household_id
                          AND budget_profiles.name IN ('Personal', 'Household')
                        ORDER BY CASE name WHEN 'Household' THEN 0 ELSE 1 END
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL
                """))
                # Accounts → Personal profile
                await conn.execute(text("""
                    UPDATE budget_accounts
                    SET profile_id = (
                        SELECT id FROM budget_profiles
                        WHERE budget_profiles.household_id = budget_accounts.household_id
                          AND budget_profiles.name = 'Personal'
                        LIMIT 1
                    )
                    WHERE profile_id IS NULL
                """))
            logger.info("budget-009 profile assignment migration complete")
        except Exception as exc:
            logger.warning("budget-009 profile assignment migration failed (non-fatal): %s", exc)

        # Ensure default categories (Household, Gifts) exist for every household.
        # Runs after profiles are seeded and assigned so profile_id is available.
        # Idempotent — skips categories that already exist by name.
        try:
            import uuid as _uuid_mod2
            async with engine.begin() as conn:
                defaults = [
                    # (name, default_scope, group_name, icon, color)
                    ("Household", "private", "Irregular / True Expenses", "🛋️", "#b45309"),
                    ("Gifts",     "private", "Irregular / True Expenses", "🎁", "#db2777"),
                ]
                rows = await conn.execute(text(
                    "SELECT DISTINCT bp.household_id, bp.id AS profile_id "
                    "FROM budget_profiles bp WHERE bp.name = 'Personal'"
                ))
                for hh_id, profile_id in rows.fetchall():
                    for cat_name, scope, group_name, icon, color in defaults:
                        exists = await conn.execute(
                            text("SELECT 1 FROM budget_categories WHERE household_id = :hh AND name = :n LIMIT 1"),
                            {"hh": hh_id, "n": cat_name},
                        )
                        if exists.fetchone():
                            # Back-fill icon/color using COALESCE — preserves any
                            # user-set value, only fills in columns that are still NULL.
                            await conn.execute(
                                text("UPDATE budget_categories "
                                     "SET icon = COALESCE(icon, :icon), color = COALESCE(color, :color) "
                                     "WHERE household_id = :hh AND name = :n"),
                                {"icon": icon, "color": color, "hh": hh_id, "n": cat_name},
                            )
                            continue
                        new_id = _uuid_mod2.uuid4().hex  # 32-char hex, no hyphens — matches ORM format
                        grp = await conn.execute(
                            text("SELECT id FROM budget_category_groups WHERE household_id = :hh AND name = :gn LIMIT 1"),
                            {"hh": hh_id, "gn": group_name},
                        )
                        grp_row = grp.fetchone()
                        grp_id = grp_row[0] if grp_row else None
                        await conn.execute(text(
                            "INSERT INTO budget_categories "
                            "(id, household_id, profile_id, name, default_scope, icon, color, "
                            " rollover_enabled, is_recurring_revenue, sort_order, group_id, created_at, updated_at) "
                            "VALUES (:id, :hh, :pid, :name, :scope, :icon, :color, 0, 0, 99, :gid, datetime('now'), datetime('now'))"
                        ), {"id": new_id, "hh": hh_id, "pid": profile_id,
                            "name": cat_name, "scope": scope, "icon": icon, "color": color, "gid": grp_id})
                        logger.info("Seeded default category '%s' for household %s", cat_name, hh_id)
            logger.info("Default category seeding complete")
        except Exception as exc:
            logger.warning("Default category seeding failed (non-fatal): %s", exc)

        # Normalize any budget_category IDs that were stored as 36-char UUID strings
        # (with hyphens) instead of 32-char hex.  This can happen when categories were
        # inserted via raw SQL using str(uuid4()) rather than uuid4().hex.  The analytics
        # LEFT JOIN on category_id = budget_categories.id silently fails when formats
        # don't match, causing affected categories to appear as Uncategorized.
        try:
            async with engine.begin() as conn:
                bad_ids = await conn.execute(text(
                    "SELECT id FROM budget_categories WHERE length(id) = 36"
                ))
                rows_fixed = 0
                for (old_id,) in bad_ids.fetchall():
                    new_id = old_id.replace("-", "")
                    # Update the primary key
                    await conn.execute(
                        text("UPDATE budget_categories SET id = :new WHERE id = :old"),
                        {"new": new_id, "old": old_id},
                    )
                    # Update any FK references in transactions
                    await conn.execute(
                        text("UPDATE budget_transactions SET category_id = :new WHERE category_id = :old"),
                        {"new": new_id, "old": old_id},
                    )
                    rows_fixed += 1
                if rows_fixed:
                    logger.info("UUID normalizer: fixed %d hyphenated category ID(s)", rows_fixed)
        except Exception as exc:
            logger.warning("UUID normalization failed (non-fatal): %s", exc)

    async with AsyncSessionLocal() as db:
        bootstrapped = await run_bootstrap_if_needed(db)
        if bootstrapped:
            logger.info("Bootstrap complete — initial password has been set")

    # AI coach Phase 2: ensure every household has at least one collection
    # tagged kind='journal' so the coach's narrative fetch and the journal
    # signal extractor can find journal entries. Runs on every boot —
    # idempotent (each household is checked + tagged or seeded at most
    # once per boot). Needed in addition to migration 0032 because the
    # migration's data backfill is Postgres-only.
    try:
        from life_dashboard.domains.collections.service import backfill_journal_kind
        async with AsyncSessionLocal() as db:
            counts = await backfill_journal_kind(db)
        if counts["tagged"] or counts["seeded"]:
            logger.info(
                "Journal-kind backfill: tagged=%d, seeded=%d, already-tagged=%d",
                counts["tagged"], counts["seeded"], counts["skipped"],
            )
    except Exception as exc:
        logger.warning("Journal-kind backfill failed (non-fatal): %s", exc)

    # ── AI Coach scheduler ────────────────────────────────────────────────────
    # Generates morning and evening digests for all eligible users.
    # Uses APScheduler's AsyncIOScheduler so jobs run in the same event loop
    # as FastAPI — no thread pool or subprocess needed.
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()

        # Morning digest: 7:00 AM each day — ready when you wake up.
        scheduler.add_job(
            run_scheduled_digests,
            CronTrigger(hour=7, minute=0),
            args=["morning"],
            id="coach_morning",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Evening digest: 5:30 PM each day — end-of-workday wind-down.
        scheduler.add_job(
            run_scheduled_digests,
            CronTrigger(hour=17, minute=30),
            args=["evening"],
            id="coach_evening",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Weekly digest: 5:00 PM every Friday — week-in-review summary.
        scheduler.add_job(
            run_scheduled_digests,
            CronTrigger(day_of_week="fri", hour=17, minute=0),
            args=["weekly"],
            id="coach_weekly",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Phase 4: weekly profile refresh — runs Sunday 3:00 AM (low-traffic
        # slot, well clear of the morning digest). For each user with a
        # non-empty profile, integrates durable patterns from the last 4
        # weeks and decays stale content. Biased toward SKIP — most weeks
        # are no-ops, which is the correct outcome.
        async def _run_scheduled_profile_refresh_with_logging():
            try:
                from life_dashboard.ai.profile_service import run_scheduled_profile_refresh_all
                counts = await run_scheduled_profile_refresh_all()
                logger.info(
                    "Scheduled profile refresh: users=%d applied=%d skip=%d "
                    "skipped_no_activity=%d error=%d",
                    counts["users"], counts["applied"], counts["skip"],
                    counts["skipped_no_activity"], counts["error"],
                )
            except Exception:
                logger.exception("Scheduled profile refresh job failed")

        scheduler.add_job(
            _run_scheduled_profile_refresh_with_logging,
            CronTrigger(day_of_week="sun", hour=3, minute=0),
            id="profile_scheduled_refresh",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Teller background sync: pull new bank transactions every 4 hours
        # for all households with linked accounts.  Runs at :00 on hours
        # 0, 4, 8, 12, 16, 20 — staggered 30 min from digests to avoid
        # simultaneous DB load.
        scheduler.add_job(
            sync_all_teller_accounts_globally,
            CronTrigger(hour="*/4", minute=30),
            id="teller_background_sync",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        scheduler.start()
        logger.info(
            "AI coach scheduler started (morning=07:00, evening=17:30, "
            "weekly=Fri 17:00, profile_refresh=Sun 03:00, teller_sync=*/4h:30)"
        )
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

# ── Rate limiting ─────────────────────────────────────────────────────────────
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(Exception)
async def _log_unhandled_exception(request: Request, exc: Exception):
    """Catch every unhandled exception, log it with a full traceback, and
    return a generic 500 so the client still gets a proper JSON response."""
    tb = traceback.format_exc()
    logging.getLogger("life_dashboard.errors").error(
        "Unhandled exception on %s %s\n%s", request.method, request.url.path, tb
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
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
app.include_router(budget_router)


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
