"""Asynchrone Datenbank-Session und Lifecycle-Management für AetherMesh."""

from __future__ import annotations

import datetime
from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.models import Base

settings = get_settings()

# Engine-Konfiguration mit SQLite-Optimierungen
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
engine_kwargs = {"connect_args": connect_args, "echo": settings.DEBUG}

# Für In-Memory-SQLite bei Tests StaticPool erzwingen
if ":memory:" in settings.DATABASE_URL:
    engine_kwargs["poolclass"] = StaticPool

engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class WorkerNode(Base):
    """Zustandsüberwachung und Heartbeat registrierter Worker-Knoten."""

    __tablename__ = "worker_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    hostname: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active, busy, draining, offline
    current_job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True
    )
    registered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


async def init_db() -> None:
    """Initialisiert alle Datenbanktabellen asynchron (Auto-Setup)."""
    # Importiere alle Modelle, damit Base.metadata alle Tabellen kennt
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Schließt die Engine-Verbindung geordnet (Graceful Shutdown)."""
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency für asynchrone DB-Sessions."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
