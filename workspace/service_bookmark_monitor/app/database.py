"""Datenbank-Konfiguration für service_bookmark_monitor.

- Default: sqlite+aiosqlite in-memory (eine gemeinsame DB über alle Verbindungen
  via `StaticPool`, da `:memory:` pro Verbindung sonst eine eigene DB wäre).
- Stellt `Base` (declarative Basis), `engine`, `SessionLocal` und die
  FastAPI-Dependency `get_db` bereit.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,   # EINE gemeinsame :memory:-DB über alle Verbindungen
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Basisklasse für alle ORM-Modelle."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI-Dependency: yieldet eine Session und schließt sie zuverlässig."""
    async with SessionLocal() as session:
        yield session