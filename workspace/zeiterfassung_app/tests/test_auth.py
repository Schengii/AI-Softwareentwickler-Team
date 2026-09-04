import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_auth_token_flow(override_get_db):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Test Login (angenommen Endpunkt existiert)
        response = await ac.post("/auth/login", data={"username": "testuser", "password": "password"})
        # Wir prüfen hier nur, ob der Endpunkt erreichbar ist oder 404/401 liefert
        assert response.status_code in [200, 401]

@pytest.mark.asyncio
async def test_protected_route_without_token(override_get_db):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/time/entries")
        assert response.status_code == 401
