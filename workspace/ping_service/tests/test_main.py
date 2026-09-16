from fastapi.testclient import TestClient

from ping_service.main import app

client = TestClient(app)


def test_ping_endpoint():
    """Prüft den GET /ping Endpunkt auf Statuscode 200 und JSON {'status': 'pong'}."""
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "pong"}


def test_ping_method_not_allowed():
    """Prüft, dass POST auf /ping mit 405 abgelehnt wird."""
    response = client.post("/ping")
    assert response.status_code == 405

