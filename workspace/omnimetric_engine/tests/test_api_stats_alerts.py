import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(scope="function")
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_get_metric_stats_success(async_client: AsyncClient):
    """Testet, ob Statistiken nach dem Ingest korrekt abgerufen werden können."""
    # Metrik einsenden
    payload = {"name": "test_metric", "value": 42.0, "timestamp": "2023-10-25T10:00:00Z"}
    response = await async_client.post("/api/v1/ingest", json=payload)
    assert response.status_code == 202
    
    # Warten, damit der asynchrone anomaly_worker die Metrik verarbeiten kann
    await asyncio.sleep(0.5)
    
    # Statistiken abrufen
    response = await async_client.get("/api/v1/stats/test_metric")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_metric"
    assert data["count"] >= 1

@pytest.mark.asyncio
async def test_get_alerts_with_data(async_client: AsyncClient):
    """Testet, ob Anomalien korrekt erkannt und als Alerts bereitgestellt werden."""
    # Baseline aufbauen (mindestens 5-10 Events für Z-Score/Mittelwert)
    for i in range(10):
        payload = {"name": "anomaly_metric", "value": 10.0, "timestamp": f"2023-10-25T10:00:{i:02d}Z"}
        res = await async_client.post("/api/v1/ingest", json=payload)
        assert res.status_code == 202
        
    # Kurze Pause für die Verarbeitung der Baseline
    await asyncio.sleep(0.5)
    
    # Anomalie einsenden (Spike)
    payload = {"name": "anomaly_metric", "value": 1000.0, "timestamp": "2023-10-25T10:01:00Z"}
    res = await async_client.post("/api/v1/ingest", json=payload)
    assert res.status_code == 202
    
    # Warten, damit der anomaly_worker die Anomalie verarbeiten und den Alert generieren kann
    await asyncio.sleep(0.5)
    
    # Alerts abrufen
    response = await async_client.get("/api/v1/alerts")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    
    # Prüfen, ob unser Alert dabei ist
    alert_found = any(alert["name"] == "anomaly_metric" for alert in data)
    assert alert_found, "Erwarteter Alert für 'anomaly_metric' wurde nicht gefunden"
