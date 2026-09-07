import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Setze den Host-Header explizit auf einen erlaubten Wert
        ac.headers["Host"] = "localhost"
        yield ac

@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_get_vehicles(client):
    response = await client.get("/api/v1/vehicles")
    assert response.status_code == 200
    assert "vehicles" in response.json()
