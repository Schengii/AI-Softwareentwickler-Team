import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_openapi_available():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Zeiterfassung API"


@pytest.mark.asyncio
async def test_auth_root():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/")
        assert response.status_code == 200
        assert "message" in response.json()


@pytest.mark.asyncio
async def test_users_root():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/users/")
        assert response.status_code == 200
        assert "message" in response.json()


@pytest.mark.asyncio
async def test_docs_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/docs")
        assert response.status_code == 200
