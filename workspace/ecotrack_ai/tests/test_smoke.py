from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_app_starts_and_health_ok():
    """Smoke-Test: Prüft, ob die App startet und der Health-Endpunkt erreichbar ist."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "status" in response.json()
    assert response.json()["status"] == "ok"
