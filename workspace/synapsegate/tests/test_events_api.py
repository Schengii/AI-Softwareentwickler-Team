from fastapi.testclient import TestClient

from app.api.v1.events import EventResponse
from app.main import app

client = TestClient(app)

def test_create_event_success():
    """Testet das erfolgreiche Erstellen eines Events."""
    payload = {"type": "test_event", "payload": {"key": "value"}}
    response = client.post("/api/v1/events/", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "event_id" in data
    assert data["status"] == "accepted"
    # Validierung gegen das Pydantic-Modell
    assert isinstance(EventResponse.model_validate(data), EventResponse)

def test_create_event_validation_error():
    """Testet Validierungsfehler bei ungültigem Payload."""
    # Fehlendes 'type' Feld
    payload = {"payload": {"key": "value"}}
    response = client.post("/api/v1/events/", json=payload)
    assert response.status_code == 422

def test_get_dlq_success():
    """Testet den Abruf der Dead Letter Queue."""
    response = client.get("/api/v1/events/dlq")
    assert response.status_code == 200
    data = response.json()
    assert "dlq" in data
    assert isinstance(data["dlq"], list)
