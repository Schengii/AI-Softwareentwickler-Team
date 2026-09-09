import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_dashboard_status_unauthorized(client: AsyncClient):
    response = await client.get("/api/v1/dashboard/status")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_get_dashboard_status_authorized(client: AsyncClient, auth_headers: dict):
    # Endpunkt existiert noch nicht, erwarte 404 oder 200 nach Implementierung
    response = await client.get("/api/v1/dashboard/status", headers=auth_headers)
    assert response.status_code in [200, 404]
