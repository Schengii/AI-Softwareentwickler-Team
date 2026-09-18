import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, engine, get_async_session
from app.main import app


# Test-Datenbank-Setup
async def override_get_async_session():
    async with AsyncSession(engine) as session:
        yield session

app.dependency_overrides[get_async_session] = override_get_async_session

@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_app_starts_and_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_event_ingestion_and_idempotency(client):
    event_payload = {
        "topic": "test-topic",
        "payload": {"foo": "bar"},
        "idempotency_key": "unique-key-123"
    }
    
    # Erstes Senden
    response1 = await client.post("/api/v1/events", json=event_payload)
    assert response1.status_code in [200, 201]
    
    # Zweites Senden (Duplikat)
    response2 = await client.post("/api/v1/events", json=event_payload)
    assert response2.status_code == 200
    assert response2.json() == response1.json()

@pytest.mark.asyncio
async def test_metrics_endpoint_exists(client):
    response = await client.get("/api/v1/metrics")
    # Erwartet 200, auch wenn noch keine Daten da sind
    assert response.status_code == 200
    assert "success_rate" in response.json()
