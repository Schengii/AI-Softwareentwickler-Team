from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

# Nutzung von aiosqlite für asynchrone DB-Operationen
DATABASE_URL = "sqlite+aiosqlite:///./analytics.db"

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def init_db():
    """
    Erstellt alle Tabellen. Muss im FastAPI lifespan-Handler aufgerufen werden:
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_async_session():
    async with SessionLocal() as session:
        yield session
