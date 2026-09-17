from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# If using memory, use StaticPool
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
poolclass = StaticPool if ":memory:" in settings.DATABASE_URL else None

engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=settings.DEBUG, 
    connect_args=connect_args,
    poolclass=poolclass
)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        yield session
