import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    """TestClient für die gesamte Testmodul-Session."""
    with TestClient(app) as c:
        yield c

def test_app_starts_and_health_ok(client: TestClient):
    """Smoke-Test: prüft, dass die Anwendung startet und /health 200 zurückgibt."""
    response = client.get("/health")
    assert response.status_code == 200
    # Erwartetes JSON-Format prüfen
    json_data = response.json()
    assert isinstance(json_data, dict)
    assert json_data.get("status") == "ok"
