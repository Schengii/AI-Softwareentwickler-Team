"""Datenbank-Konfiguration und Session-Management für IncidentPulse."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# Einstellungen laden
settings = get_settings()

database_url = getattr(settings, "DATABASE_URL", "sqlite+aiosqlite:///./incidentpulse.db")
# Sicherstellen, dass für async SQLite aiosqlite genutzt wird
if database_url.startswith("sqlite:///") and not database_url.startswith("sqlite+aiosqlite:///"):
    database_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")

engine = create_async_engine(
    database_url,
    echo=False,
    future=True,
)

async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency zur Bereitstellung einer asynchronen Datenbanksitzung."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
