# app/db/base.py
from sqlmodel import SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.ext.asyncio.session import async_sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jobsuche.db")

engine = create_engine(DATABASE_URL, echo=False, future=True)

async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def create_db_and_tables():
    """Erstellt alle Tabellen (nur für Entwicklungs‑/Demo‑Umgebung)."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

# Dependency
async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
