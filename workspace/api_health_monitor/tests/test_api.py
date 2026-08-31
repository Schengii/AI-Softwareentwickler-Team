import pytest
from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient
from app.main import app
from app.monitor.checker import monitor

@pytest.fixture
async def client():
    # Reset monitor state before each test
    monitor.checks = {}
    monitor.subscribers = set()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_get_checks_empty(client):
    response = await client.get("/checks")
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_create_check(client):
    new_check = {"url": "http://example.com"}
    response = await client.post("/checks", json=new_check)
    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "http://example.com"
    assert "id" in data
    assert len(monitor.checks) == 1

def test_websocket_connection():
    # httpx.AsyncClient hat keinen websocket_connect - dafür braucht es einen
    # echten ASGI-Testclient (starlette/fastapi TestClient) statt httpx.
    monitor.checks = {}
    monitor.subscribers = set()
    with TestClient(app).websocket_connect("/ws/live") as websocket:
        assert len(monitor.subscribers) == 1
        # Test basic handshake
        websocket.send_text("ping")

    # After closing, subscriber should be removed
    assert len(monitor.subscribers) == 0
