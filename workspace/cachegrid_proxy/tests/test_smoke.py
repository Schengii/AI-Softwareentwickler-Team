from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_app_starts_and_health_ok():
    """Smoke-Test: Prüft, ob die App startet und der Health-Endpoint erreichbar ist."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
