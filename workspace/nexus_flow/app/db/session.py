from collections.abc import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base

settings = get_settings()

engine_kwargs: dict = {
    "echo": settings.DEBUG,
    "connect_args": {"check_same_thread": False},
}

if ":memory:" in settings.DATABASE_URL:
    engine_kwargs["poolclass"] = StaticPool

engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# WAL-Modus und Foreign Keys für SQLite aktivieren
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if ":memory:" not in settings.DATABASE_URL:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency für asynchrone Datenbank-Sessions."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialisiert das Datenbankschema asynchron."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
