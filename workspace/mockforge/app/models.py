from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite+aiosqlite:///./mockforge.db"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class MockDefinition(AsyncAttrs, Base):
    __tablename__ = "mocks"
    id = Column(Integer, primary_key=True, index=True)
    method = Column(String, index=True)
    path_pattern = Column(String, index=True)
    response_status = Column(Integer)
    response_body = Column(Text)
    is_active = Column(Boolean, default=True)

class TrafficLog(AsyncAttrs, Base):
    __tablename__ = "traffic_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(String)
    method = Column(String)
    url = Column(String)
    request_headers = Column(Text)
    request_body = Column(Text)
    response_status = Column(Integer)
    response_body = Column(Text)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
