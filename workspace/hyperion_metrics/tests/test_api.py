import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_app_starts_and_health_ok():
    """Smoke-Test: Prüft, ob die App startet und der Health-Endpoint erreichbar ist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_ingestion_endpoint_accepts_metric():
    """Prüft den POST /api/v1/metrics Endpunkt."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "name": "cpu_usage",
            "value": 45.5,
            "timestamp": 1700000000.0
        }
        response = await client.post("/api/v1/metrics", json=payload)
        assert response.status_code == 202
