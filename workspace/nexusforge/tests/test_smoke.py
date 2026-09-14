import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_smoke_app_startup_and_health():
    """Verifiziert grundlegenden App-Start und OpenAPI/Health-Routen."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/docs")
        assert response.status_code == 200
