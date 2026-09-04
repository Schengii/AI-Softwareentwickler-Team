import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_read_index(client):
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_and_get_mocks(client):
    payload = {
        "method": "GET",
        "path_pattern": "/test",
        "response_status": 200,
        "response_body": '{"status": "ok"}',
        "is_active": True
    }
    response = await client.post("/api/v1/mocks", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["path_pattern"] == "/test"

    response = await client.get("/api/v1/mocks")
    assert response.status_code == 200
    mocks = response.json()
    assert len(mocks) >= 1


@pytest.mark.asyncio
async def test_get_logs(client):
    response = await client.get("/api/v1/logs")
    assert response.status_code == 200
