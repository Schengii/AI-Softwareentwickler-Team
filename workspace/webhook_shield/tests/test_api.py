"""Test-Suite für die WebhookShield API.

Abgedeckte Szenarien:
- POST /webhooks/{endpoint_path} → 404 bei unbekanntem Endpunkt
- POST /webhooks/{endpoint_path} → 200 + Persistenz-Roundtrip (Schreiben-dann-Lesen)
- POST /webhooks/{endpoint_path} → 400 bei ungültigem JSON-Body (kein 500)
- GET /logs → liefert persistierte DeliveryLogs zurück
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app, get_db
from app.models import Base, Webhook

# In-Memory-SQLite für Tests (echte Isolation, kein Datei-Restmüll wie test.db)
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Erzwingt die In-Memory-Test-DB für alle Requests (sonst greift die App auf
    ihre Produktions-DB webhookshield.db zu → 'no such table')."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function", autouse=True)
def setup_db():
    """Legt pro Test ein sauberes Schema an und räumt danach wieder auf."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _create_webhook(endpoint_path: str = "test-endpoint", hmac_secret: str = "test-secret") -> Webhook:
    """Legt einen Webhook-Eintrag mit ALLEN Pflichtfeldern an.

    hmac_secret ist im Modell als nullable=False deklariert – ohne Wert
    schlägt db.commit() mit IntegrityError fehl (bekannter Befund).
    """
    db = TestingSessionLocal()
    webhook = Webhook(endpoint_path=endpoint_path, hmac_secret=hmac_secret)
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    db.close()
    return webhook


@pytest.mark.asyncio
async def test_receive_webhook_404(client):
    """Unbekannter Endpunkt → 404, kein Log-Eintrag."""
    response = await client.post("/webhooks/non-existent", json={"event": "x"})
    assert response.status_code == 404

    logs = await client.get("/logs")
    assert logs.json() == []


@pytest.mark.asyncio
async def test_receive_webhook_success(client):
    """Bekannter Endpunkt → 200 'accepted' UND Daten sind wirklich persistiert.

    Roundtrip: erst POST, dann GET /logs – verifiziert, dass der Payload
    tatsächlich gespeichert wurde (nicht nur Response-Echo).
    """
    _create_webhook()

    payload = {"event": "test", "data": 123}
    response = await client.post("/webhooks/test-endpoint", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["log_id"] > 0

    # Roundtrip-Verifikation über GET /logs
    logs = await client.get("/logs")
    logs_json = logs.json()
    assert len(logs_json) == 1
    assert logs_json[0]["payload_json"] == payload
    assert logs_json[0]["status"] == "received"
    assert logs_json[0]["webhook_id"] == 1


@pytest.mark.asyncio
async def test_receive_webhook_invalid_json(client):
    """Ungültiger JSON-Body → 400 (kein 500): OWASP-Webhook-Praxis,
    Eingaben strikt validieren statt Traceback an den Absender zu leaken."""
    _create_webhook()

    response = await client.post(
        "/webhooks/test-endpoint",
        content=b"{invalid-json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_receive_webhook_empty_body(client):
    """Leerer Body → 400 (kein 500)."""
    _create_webhook()

    response = await client.post("/webhooks/test-endpoint", content=b"")

    assert response.status_code == 400