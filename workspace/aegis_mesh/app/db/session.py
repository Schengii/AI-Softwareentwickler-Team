"""Datenbank-Session-Management und Engine-Konfiguration für AegisMesh.

Strikte Single-DB-Architektur mit asynchronem SQLAlchemy (aiosqlite).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

__all__ = [
    "Base",
    "async_session_factory",
    "close_db",
    "engine",
    "get_db_session",
    "init_db",
]


class Base(DeclarativeBase):
    """Zentrale DeclarativeBase für alle SQLAlchemy-Modelle des Projekts."""


settings = get_settings()

# Asynchrone SQLite-Engine
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    connect_args={"check_same_thread": False},
)

# Asynchroner Session-Maker
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency-Generator zur Bereitstellung einer asynchronen DB-Session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Erstellt alle definierten Tabellen asynchron im Lifespan-Handler."""
    # Importiere Modelle hier, damit alle Mappings an Base.metadata registriert sind
    import app.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Schließt die Engine-Verbindungen geordnet beim Herunterfahren."""
    await engine.dispose()
