import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# Test-Datenbank Konfiguration
DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_get_stats_empty(client):
    response = await client.get("/api/v1/stats")
    assert response.status_code == 200
    assert response.json() == {}

@pytest.mark.asyncio
async def test_event_roundtrip_and_stats(client):
    # 1. Event senden
    payload = {"event_type": "test_event", "payload": {"key": "value"}}
    response = await client.post("/api/v1/events", json=payload)
    assert response.status_code == 200
    
    # 2. Stats prüfen
    stats_response = await client.get("/api/v1/stats")
    assert stats_response.status_code == 200
    assert len(stats_response.json()) > 0

@pytest.mark.asyncio
async def test_get_events_list(client):
    response = await client.get("/api/v1/events")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
