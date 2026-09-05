import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, get_db
from app.models import Base

# In-Memory Datenbank für Tests
DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def client():
    async def override_get_db():
        async with TestingSessionLocal() as session:
            yield session
    
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_read_index(client):
    response = await client.get("/")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_create_and_get_mocks(client):
    payload = {
        "method": "GET",
        "path_pattern": "/test",
        "response_status": 200,
        "response_body": '{"status": "ok"}',
        "is_active": True
    }
    response = await client.post("/api/v1/mocks", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["path_pattern"] == "/test"

    response = await client.get("/api/v1/mocks")
    assert response.status_code == 200
    mocks = response.json()
    assert len(mocks) == 1
    assert mocks[0]["path_pattern"] == "/test"

@pytest.mark.asyncio
async def test_get_logs(client):
    response = await client.get("/api/v1/logs")
    assert response.status_code == 200
    assert response.json() == []
