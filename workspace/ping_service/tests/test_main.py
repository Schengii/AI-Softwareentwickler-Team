"""Tests für den Ping-Service (main.py)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_smoke_health_endpoint():
    """Smoke-Test: Prüft, ob die Anwendung startet und der Health-Check 200 OK liefert."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_get_ping_returns_200_and_pong():
    """Akzeptanzkriterium: GET /ping gibt Status 200 und {'status': 'pong'} zurück."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ping")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "pong"}


@pytest.mark.asyncio
async def test_post_ping_method_not_allowed():
    """Prüft, dass nicht unterstützte HTTP-Methoden auf /ping 405 zurückgeben."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/ping")
    assert response.status_code == 405
