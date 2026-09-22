"""Smoke-Tests für den Webhook Sentinel Service.

Diese Tests prüfen, ob die FastAPI-Anwendung startet und die Grund-Health-Route
sowie die Root-Route funktionieren. Sie dienen als erstes Gate: Scheitern sie,
sind alle weiterführenden Tests sinnlos.

Geprüfte Endpunkte (existieren tatsächlich in app/main.py):
- GET /health -> {"status": "ok"}
- GET /       -> {"message": "Webhook Sentinel API"}
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    """AsyncClient mit ASGITransport, der die App ohne echten HTTP-Server bedient."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_app_starts_and_health_ok(client):
    """Die App startet und /health liefert 200 mit Status 'ok'."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_root_route_ok(client):
    """Die Root-Route liefert 200 mit dem API-Namen."""
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Webhook Sentinel API"}