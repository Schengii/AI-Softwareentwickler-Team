import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_read_log(client: AsyncClient):
    # Test-Daten
    log_data = {
        "level": "INFO",
        "source": "test-service",
        "message": "Test log entry"
    }

    # 1. Schreiben (POST)
    response = await client.post("/api/v1/logs", json=log_data)
    assert response.status_code == 200
    data = response.json()
    assert data["level"] == log_data["level"]
    assert data["source"] == log_data["source"]
    assert data["message"] == log_data["message"]
    assert "id" in data

    # 2. Lesen (GET) - Roundtrip-Verifizierung
    response = await client.get("/api/v1/logs")
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 1
    assert logs[0]["id"] == data["id"]
    assert logs[0]["message"] == log_data["message"]

@pytest.mark.asyncio
async def test_filter_logs(client: AsyncClient):
    # Erstelle zwei Logs
    await client.post("/api/v1/logs", json={"level": "INFO", "source": "A", "message": "1"})
    await client.post("/api/v1/logs", json={"level": "ERROR", "source": "B", "message": "2"})

    # Filter nach Level
    response = await client.get("/api/v1/logs?level=ERROR")
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 1
    assert logs[0]["level"] == "ERROR"

    # Filter nach Source
    response = await client.get("/api/v1/logs?source=A")
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 1
    assert logs[0]["source"] == "A"
