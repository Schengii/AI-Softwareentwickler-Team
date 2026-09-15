from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.dispatcher import dispatcher
from app.main import EndpointOut, EventOut, app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(autouse=True)
async def prepare_database():
    """Erstellt Test-Tabellen im In-Memory SQLite vor jedem Testlauf."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Smoke-Test: Health-Check Endpunkt antwortet mit Status 200."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_and_list_endpoints(client: AsyncClient):
    """Roundtrip-Test: Endpunkt anlegen und über GET /endpoints abrufen."""
    payload = {
        "url": "https://example.com/webhook",
        "secret": "top-secret-123",
        "description": "Test Webhook Endpoint",
    }
    response = await client.post("/endpoints", json=payload)
    assert response.status_code == 200
    data = response.json()
    validated = EndpointOut.model_validate(data)
    assert validated.url == payload["url"]
    assert validated.description == payload["description"]

    list_response = await client.get("/endpoints")
    assert list_response.status_code == 200
    endpoints = list_response.json()
    assert len(endpoints) == 1
    assert endpoints[0]["id"] == validated.id


@pytest.mark.asyncio
async def test_create_event(client: AsyncClient):
    """Test: Event annehmen und Hintergrund-Dispatcher aufrufen."""
    with patch.object(dispatcher, "dispatch_event", new_callable=AsyncMock) as mock_dispatch:
        payload = {"payload": {"message": "hello world", "code": 42}}
        response = await client.post("/events", json=payload)
        assert response.status_code == 200
        data = response.json()
        validated = EventOut.model_validate(data)
        assert validated.payload == payload["payload"]
        assert validated.id is not None
        mock_dispatch.assert_called_once_with(validated.id)
