import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from life_dashboard.ai.router import router as ai_router
from life_dashboard.auth.router import router as auth_router
from life_dashboard.households.router import router as households_router
from life_dashboard.uploads.router import router as uploads_router
from life_dashboard.domains.calendar_events.router import router as calendar_events_router
from life_dashboard.domains.collections.router import router as collections_router
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
from life_dashboard.domains.workouts.router import router as workouts_router
from life_dashboard.auth.service import run_bootstrap_if_needed
from life_dashboard.setup.router import router as setup_router
from life_dashboard.core.database import AsyncSessionLocal, engine
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

    async with AsyncSessionLocal() as db:
        bootstrapped = await run_bootstrap_if_needed(db)
        if bootstrapped:
            logger.info("Bootstrap complete — initial password has been set")

    yield

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(setup_router)
app.include_router(ai_router)
app.include_router(auth_router)
app.include_router(households_router)
app.include_router(uploads_router)
app.include_router(calendar_events_router)
app.include_router(collections_router)
app.include_router(contacts_router)
app.include_router(documents_router)
app.include_router(goals_router)
app.include_router(projects_router)
app.include_router(grocery_lists_router)
app.include_router(habits_router)
app.include_router(notes_router)
app.include_router(recipes_router)
app.include_router(tags_router)
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
