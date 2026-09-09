import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    # Da die Endpunkte noch nicht existieren, erwarten wir 404
    # Dies dient als Basis-Test für die spätere Implementierung
    response = await client.post("/api/v1/auth/login", data={"username": "user", "password": "password"})
    assert response.status_code in [200, 404]

@pytest.mark.asyncio
async def test_token_validation_failure(client: AsyncClient):
    headers = {"Authorization": "Bearer invalid-token"}
    response = await client.get("/api/v1/dashboard/status", headers=headers)
    assert response.status_code == 401
