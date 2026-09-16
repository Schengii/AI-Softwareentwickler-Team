"""Testsuite für die Haupt-Endpunkte der FastAPI-Anwendung."""

import pytest
from fastapi.testclient import TestClient

try:
    from ping_service.main import app
except ImportError:
    from main import app


@pytest.fixture(scope="function")
def client() -> TestClient:
    """Fixture zur Bereitstellung eines FastAPI TestClients."""
    with TestClient(app) as test_client:
        yield test_client


def test_app_starts_and_health_ok(client: TestClient) -> None:
    """Smoke-Test: Prüft, ob die App startet und der Health-Endpunkt erreichbar ist."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_ping_returns_200_and_exact_json(client: TestClient) -> None:
    """Prüft, dass GET /ping Status 200 und exakt {'status': 'pong'} liefert."""
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "pong"}


def test_ping_post_method_not_allowed(client: TestClient) -> None:
    """Prüft, dass nicht unterstützte HTTP-Methoden wie POST auf /ping mit 405 abgewiesen werden."""
    response = client.post("/ping")
    assert response.status_code == 405
