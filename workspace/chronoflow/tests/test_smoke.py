from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_app_starts_and_health_ok():
    """Smoke-Test: Prüft, ob die App startet und die Root-Route erreichbar ist."""
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200

def test_api_saga_endpoints_exist():
    """Testet, ob die API-Endpunkte grundsätzlich definiert sind."""
    with TestClient(app) as client:
        response = client.post("/api/v1/sagas", json={"workflow_type": "test", "payload": {}})
        assert response.status_code != 404
