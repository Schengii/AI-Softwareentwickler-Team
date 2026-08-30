import pytest
from httpx import AsyncClient
from fastapi.testclient import TestClient

from app.main import app

@pytest.mark.asyncio
async def test_list_tasks_empty():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_create_task_validation():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/tasks", json={})
    assert response.status_code == 422

def test_websocket_broadcast():
    client = TestClient(app)
    with client.websocket_connect("/ws/tasks") as websocket:
        # Erstelle ein Task über HTTP REST
        res = client.post("/tasks", json={"title": "WS Task Test", "status": "Todo"})
        assert res.status_code == 201
        
        # Empfange Broadcast-Payload über WebSocket
        data = websocket.receive_json()
        assert data["title"] == "WS Task Test"
        assert data["status"] == "Todo"
