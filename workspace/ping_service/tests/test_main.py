"""Tests für die Hauptanwendung und den /ping-Endpunkt."""

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
def client() -> TestClient:
    """Synchroner TestClient für Standard-Anfragen."""
    return TestClient(app)


def test_app_starts_and_health_smoke(client: TestClient) -> None:
    """Smoke-Test: Prüft, ob die App startet und der Health-Endpunkt erreichbar ist."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ping_endpoint_returns_200_and_pong_json(client: TestClient) -> None:
    """Prüft, ob GET /ping Status 200 liefert und {'status': 'pong'} zurückgibt."""
    response = client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert data == {"status": "pong"}
    assert data.get("status") == "pong"


def test_ping_endpoint_headers(client: TestClient) -> None:
    """Prüft, dass der /ping-Endpunkt JSON als Content-Type deklariert."""
    response = client.get("/ping")
    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")


def test_ping_endpoint_method_not_allowed(client: TestClient) -> None:
    """Prüft, dass POST auf /ping mit HTTP 405 abgelehnt wird."""
    response = client.post("/ping")
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_ping_endpoint_async() -> None:
    """Asynchroner Test mit httpx.AsyncClient zur Validierung im async Kontext."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        response = await async_client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"status": "pong"}
