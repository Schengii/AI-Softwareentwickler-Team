from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=None # We will use StaticPool for in-memory if needed, but here we use file-based sqlite
)

# For SQLite file-based, default pool is NullPool which is fine.
# If in-memory, we would need StaticPool. Let's ensure we use StaticPool if memory.
if ":memory:" in settings.DATABASE_URL:
    from sqlalchemy.pool import StaticPool
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False}
    )

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
