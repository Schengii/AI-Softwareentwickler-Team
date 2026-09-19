import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_api_key_creation_and_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Create an API key
        response = await ac.post("/api/auth/keys", json={
            "name": "test_key",
            "scopes": "secrets:read,secrets:write,flags:read,flags:write"
        })
        assert response.status_code == 200
        data = response.json()
        assert "raw_key" in data
        raw_key = data["raw_key"]

        # 2. Use the API key to create a secret
        headers = {"X-API-Key": raw_key}
        secret_response = await ac.post("/api/secrets", json={
            "key": "test_secret",
            "value": "hidden_value",
            "ttl_seconds": 3600
        }, headers=headers)
        assert secret_response.status_code == 200
        secret_data = secret_response.json()
        assert secret_data["key"] == "test_secret"

        # 3. Read the secret back
        get_response = await ac.get("/api/secrets/test_secret", headers=headers)
        assert get_response.status_code == 200
        assert get_response.json()["value"] == "hidden_value"

        # 4. Test without API key
        no_auth_response = await ac.get("/api/secrets/test_secret")
        assert no_auth_response.status_code == 401
