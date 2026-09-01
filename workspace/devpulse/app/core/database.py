from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from app.core.config import settings

# Basis-Klasse für alle SQLAlchemy-Modelle
Base = declarative_base()

# Datenbank-Engine Konfiguration
if settings.USE_SQLITE:
    # In-Memory SQLite benötigt StaticPool, damit alle Verbindungen auf dieselbe DB zugreifen
    engine = create_async_engine(
        settings.SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    # PostgreSQL Produktion-Engine
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
    )

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    """Dependency für FastAPI-Router zur Bereitstellung der Session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
