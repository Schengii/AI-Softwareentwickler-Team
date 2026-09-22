from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from app.core.config import get_settings

settings = get_settings()

# If using in-memory sqlite, we need StaticPool and check_same_thread=False
# For file-based sqlite, check_same_thread=False is still useful for async/FastAPI
connect_args = {"check_same_thread": False}
poolclass = StaticPool if ":memory:" in settings.DATABASE_URL else None

engine_kwargs = {"echo": settings.DEBUG, "connect_args": connect_args}
if poolclass:
    engine_kwargs["poolclass"] = poolclass

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Alias für Kompatibilität mit bestehenden Tests/Code
# async_session_factory wird als Callable erwartet, das einen AsyncSession-Context-Manager liefert.
# Wir setzen es auf den async_session_maker, da dieser bereits das gewünschte Verhalten hat.
async_session_factory = async_session_maker

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
