from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# Determine if we are using an in-memory database
is_memory = ":memory:" in settings.DATABASE_URL

# Setup engine arguments
engine_kwargs = {"echo": settings.DEBUG}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    if is_memory:
        engine_kwargs["poolclass"] = StaticPool

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

# Create session factory
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db() -> AsyncSession:
    """FastAPI dependency for database sessions."""
    async with async_session() as session:
        yield session
