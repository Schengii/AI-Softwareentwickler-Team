from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from typing import AsyncGenerator

# Async SQLite Engine
engine = create_async_engine("sqlite+aiosqlite:///notes.db", echo=False, future=True)

# Session factory
async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency, liefert eine asynchrone DB‑Session."""
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Erstellt Tabellen, falls sie noch nicht existieren."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
