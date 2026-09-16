import pytest
from httpx import ASGITransport, AsyncClient

from ping_service.main import app


@pytest.mark.asyncio
async def test_ping():
    """Testet den /ping Endpunkt."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "pong"}

@pytest.mark.asyncio
async def test_health():
    """Testet den /health Endpunkt."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
