import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool
from app.database import Base, get_async_session
from app.main import app
from httpx import ASGITransport, AsyncClient

# Test-Datenbank: In-Memory SQLite
DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = create_async_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
    
    yield session
    
    await transaction.rollback()
    await connection.close()
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_async_session] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
