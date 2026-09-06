import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@respx.mock
@pytest.mark.asyncio
async def test_proxy_success(client):
    respx.get("http://internal-service.local/api/test").mock(
        return_value=Response(200, json={"data": "success"})
    )
    
    response = await client.get("/api/test")
    assert response.status_code == 200
    assert response.json() == {"data": "success"}

@respx.mock
@pytest.mark.asyncio
async def test_proxy_upstream_failure(client):
    respx.get("http://internal-service.local/fail").mock(
        return_value=Response(500)
    )
    
    response = await client.get("/fail")
    assert response.status_code == 500

@respx.mock
@pytest.mark.asyncio
async def test_proxy_connection_error(client):
    respx.get("http://internal-service.local/error").mock(side_effect=Exception("Connection refused"))
    
    response = await client.get("/error")
    assert response.status_code == 502
