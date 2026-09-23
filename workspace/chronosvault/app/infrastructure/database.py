import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

class Base(DeclarativeBase):
    pass

if ":memory:" in DATABASE_URL:
    engine = create_async_engine(
        DATABASE_URL, 
        connect_args={"check_same_thread": False}, 
        poolclass=StaticPool
    )
else:
    engine = create_async_engine(
        DATABASE_URL, 
        connect_args={"check_same_thread": False}
    )

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    async with SessionLocal() as session:
        yield session
