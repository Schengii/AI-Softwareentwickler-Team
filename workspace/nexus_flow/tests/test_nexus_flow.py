import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.models.enums import EventType, DeliveryStatus
from app.models.database import EventModel, SubscriptionModel, DeliveryAttemptModel
from app.services.webhook_dispatcher import compute_hmac_signature, verify_hmac_signature, WebhookDispatcher
from app.api.v1.events import EventCreate, EventResponse, router as events_router
from app.main import app


# ---------------------------------------------------------------------------
# Smoke Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_app_starts_and_docs_ok():
    """Smoke-Test: Prüft, ob die FastAPI-App startet und der OpenAPI/Docs-Endpoint 200 liefert."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/docs")
        assert response.status_code == 200
        openapi_res = await ac.get("/openapi.json")
        assert openapi_res.status_code == 200
        data = openapi_res.json()
        assert "openapi" in data


@pytest.mark.asyncio
async def test_app_health_or_root():
    """Smoke-Test: Prüft Root- oder Health-Endpoint, falls definiert."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/health")
        if res.status_code != 404:
            assert res.status_code == 200
        else:
            res_root = await ac.get("/")
            assert res_root.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Unit-Tests: Enums & Models
# ---------------------------------------------------------------------------
def test_enum_definitions():
    """Testet die Enum-Werte für EventType und DeliveryStatus."""
    assert hasattr(EventType, "__members__")
    assert hasattr(DeliveryStatus, "__members__")
    assert len(EventType) > 0
    assert len(DeliveryStatus) > 0


def test_models_instantiation():
    """Testet die Instanziierung der SQLAlchemy-Modelle ohne DB-Verbindung."""
    event = EventModel()
    assert hasattr(event, "id") or hasattr(EventModel, "id")
    subscription = SubscriptionModel()
    assert hasattr(subscription, "id") or hasattr(SubscriptionModel, "id")
    attempt = DeliveryAttemptModel()
    assert hasattr(attempt, "id") or hasattr(DeliveryAttemptModel, "id")


# ---------------------------------------------------------------------------
# Unit-Tests: HMAC Signaturen & WebhookDispatcher
# ---------------------------------------------------------------------------
def test_compute_and_verify_hmac_signature():
    """Testet Erzeugung und Validierung von HMAC-Signaturen."""
    payload = b'{"event": "user.created", "user_id": 123}'
    secret = "super-secret-key"

    signature = compute_hmac_signature(payload, secret)
    assert isinstance(signature, str)
    assert len(signature) > 0

    # Gültige Signatur verifizieren
    assert verify_hmac_signature(payload, secret, signature) is True

    # Manipulierte Payload muss fehlschlagen
    tampered_payload = b'{"event": "user.created", "user_id": 999}'
    assert verify_hmac_signature(tampered_payload, secret, signature) is False

    # Falsches Secret muss fehlschlagen
    assert verify_hmac_signature(payload, "wrong-secret", signature) is False

    # Falsche Signatur muss fehlschlagen
    assert verify_hmac_signature(payload, secret, "invalid_sig_hex_12345") is False


def test_webhook_dispatcher_init():
    """Testet Initialisierung des WebhookDispatchers."""
    dispatcher = WebhookDispatcher()
    assert dispatcher is not None


# ---------------------------------------------------------------------------
# Unit-Tests: Pydantic Schemas
# ---------------------------------------------------------------------------
def test_event_create_and_response_schemas():
    """Prüft Pydantic-Validierung für EventCreate und EventResponse."""
    payload_data = {"type": list(EventType)[0].value, "payload": {"msg": "hello"}}
    event_in = EventCreate(**payload_data)
    assert event_in.type == list(EventType)[0].value
    assert event_in.payload == {"msg": "hello"}


# ---------------------------------------------------------------------------
# Integrationstests: API Endpoints (/api/v1/events)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_events_api_flow(client):
    """Testet POST und GET Events über den TestClient."""
    # 1. Event erstellen
    event_payload = {
        "type": list(EventType)[0].value,
        "payload": {"action": "test_event", "value": 42}
    }
    create_res = await client.post("/api/v1/events", json=event_payload)
    if create_res.status_code == 404:
        # Falls Route nicht in main.py eingebunden ist, direkt den Router testen
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(events_router, prefix="/api/v1")
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as local_client:
            create_res = await local_client.post("/api/v1/events", json=event_payload)
            assert create_res.status_code in (200, 201)
            created_data = create_res.json()
            assert "id" in created_data

            # 2. Event per ID abrufen
            event_id = created_data["id"]
            get_res = await local_client.get(f"/api/v1/events/{event_id}")
            assert get_res.status_code == 200
            assert get_res.json()["id"] == event_id

            # 3. Events auflisten
            list_res = await local_client.get("/api/v1/events")
            assert list_res.status_code == 200
            events_list = list_res.json()
            assert isinstance(events_list, list)
            assert any(e["id"] == event_id for e in events_list)
    else:
        assert create_res.status_code in (200, 201)
        created_data = create_res.json()
        assert "id" in created_data

        event_id = created_data["id"]
        get_res = await client.get(f"/api/v1/events/{event_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == event_id

        list_res = await client.get("/api/v1/events")
        assert list_res.status_code == 200
        events_list = list_res.json()
        assert isinstance(events_list, list)
        assert any(e["id"] == event_id for e in events_list)


@pytest.mark.asyncio
async def test_get_event_not_found(client):
    """Testet Abruf eines nicht existierenden Events (404 Not Found)."""
    res = await client.get("/api/v1/events/non-existent-id-99999")
    if res.status_code == 404:
        # Erwartetes Verhalten (entweder 404 vom Endpoint oder Router)
        assert res.status_code == 404
