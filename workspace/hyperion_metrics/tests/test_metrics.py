import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_app_starts_and_health_ok():
    """Smoke-Test: Prüft, ob die App startet und erreichbar ist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200

@pytest.mark.asyncio
async def test_metrics_ingestion_endpoint():
    """
    Testet die Metrik-Ingestion.
    Der Endpunkt ist /metrics gemäß app/api/ingestion.py.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "name": "cpu_usage",
            "value": 45.5,
            "timestamp": 1726570000.0,
            "tags": {"host": "server-01"}
        }
        # POST /metrics ist in app/api/ingestion.py definiert
        response = await client.post("/metrics", json=payload)
        assert response.status_code == 202
