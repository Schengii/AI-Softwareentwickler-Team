import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, engine, get_async_session, get_db
from app.main import app
from app.models.event import EventResponse


# Test-Datenbank-Setup: Dependency-Overrides für beide Alias-Namen
async def override_get_session():
    async with AsyncSession(engine) as session:
        yield session

app.dependency_overrides[get_async_session] = override_get_session
app.dependency_overrides[get_db] = override_get_session


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_db():
    """Initialisiert und bereinigt die Tabellen vor und nach jedem Testlauf."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client():
    """Erstellt einen isolierten httpx AsyncClient mit ASGI Transport."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_app_starts_and_health_ok(client):
    """Smoke-Test: Prüft den Healthcheck-Endpunkt."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_root_dashboard_serves_html(client):
    """Prüft, ob die Root-Route das Frontend-Dashboard ausliefert."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "AegisFlow" in response.text


@pytest.mark.asyncio
async def test_event_ingestion_and_idempotency(client):
    """Testet das Erstellen von Events und die Idempotenz bei doppelter Übertragung."""
    event_payload = {
        "topic": "test-topic",
        "payload": {"foo": "bar"},
        "idempotency_key": "unique-key-123",
    }

    # Erstes Senden
    response1 = await client.post("/api/v1/events", json=event_payload)
    assert response1.status_code in [200, 201]
    data1 = response1.json()
    validated1 = EventResponse.model_validate(data1)
    assert validated1.topic == "test-topic"
    assert validated1.idempotency_key == "unique-key-123"

    # Zweites Senden (Duplikat mit demselben idempotency_key)
    response2 = await client.post("/api/v1/events", json=event_payload)
    assert response2.status_code == 200
    data2 = response2.json()
    validated2 = EventResponse.model_validate(data2)
    assert validated1.id == validated2.id
    assert validated1.topic == validated2.topic
    assert validated1.idempotency_key == validated2.idempotency_key


@pytest.mark.asyncio
async def test_event_get_roundtrip(client):
    """Roundtrip-Test: Event über API einspeisen und per ID abrufen."""
    event_payload = {
        "topic": "order-created",
        "payload": {"order_id": 42},
        "idempotency_key": "order-42-key",
    }

    create_resp = await client.post("/api/v1/events", json=event_payload)
    assert create_resp.status_code in [200, 201]
    created_event = EventResponse.model_validate(create_resp.json())

    # Lesen über GET /api/v1/events/{id}
    get_resp = await client.get(f"/api/v1/events/{created_event.id}")
    assert get_resp.status_code == 200
    fetched_event = EventResponse.model_validate(get_resp.json())
    assert fetched_event.id == created_event.id
    assert fetched_event.topic == "order-created"
    assert fetched_event.idempotency_key == "order-42-key"


@pytest.mark.asyncio
async def test_get_event_not_found(client):
    """Edge Case: Abruf eines nicht existierenden Events gibt 404."""
    response = await client.get("/api/v1/events/999999")
    assert response.status_code == 404
