from fastapi.testclient import TestClient

try:
    from ping_service.main import app
except ImportError:
    from main import app

client = TestClient(app)


def test_health_endpoint_success():
    """Prüft den GET /health Endpunkt auf Statuscode 200 und JSON-Response."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "status" in data


def test_health_method_not_allowed():
    """Prüft, dass POST auf /health mit 405 Method Not Allowed abgewiesen wird."""
    response = client.post("/health")
    assert response.status_code == 405


def test_health_delete_not_allowed():
    """Prüft, dass DELETE auf /health mit 405 Method Not Allowed abgewiesen wird."""
    response = client.delete("/health")
    assert response.status_code == 405
