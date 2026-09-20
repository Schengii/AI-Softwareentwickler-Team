import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_app_starts_and_health_ok():
    """Smoke-Test: Prüft, ob die App startet und der Health-Check erreichbar ist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Annahme: /health ist der Health-Endpoint gemäß Standard-Konvention
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
