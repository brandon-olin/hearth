from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from life_dashboard.core.settings import settings

engine = create_async_engine(
    settings.database_url,
    # Validates each connection before handing it to a query. Important for
    # long-idle pools — the NAS firewall may silently drop connections.
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=(settings.environment == "development"),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    # Prevents SQLAlchemy from expiring ORM attributes after commit, which
    # would trigger lazy-load errors in an async context.
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base — all domain models inherit from this."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session and guarantees cleanup."""
    async with AsyncSessionLocal() as session:
        yield session
