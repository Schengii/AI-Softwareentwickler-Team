import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.main import app
from app.core.database import Base, get_async_session
from app.core.config import get_settings

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="function")
async def db_session():
    test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async_session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with async_session() as session:
        yield session
        
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        
    await test_engine.dispose()

@pytest.fixture
def auth_headers():
    settings = get_settings()
    return {"X-API-Key": settings.API_KEY}

@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession):
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
