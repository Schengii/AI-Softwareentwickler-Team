import asyncio
from datetime import UTC, datetime

import pytest
from app.main import app
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


def _fresh_timestamp() -> str:
    """Aktueller Zeitstempel statt eines fest kodierten historischen Datums: `RingBuffer.
    evict_old()` (app/engine.py) verwirft beim `add()` sofort alles, was älter als
    `max_age_seconds=60` relativ zur WALLCLOCK-Zeit ist - ein Zeitstempel wie '2023-10-25T...'
    wird dadurch augenblicklich wieder entfernt, `get_stats()`/`get_alerts()` sehen dann nie
    Daten (realer Fund, root-cause-omnimetric_engine-falscher-api-pfad-oder-fehlende-daten-im-
    stats-test: die Route/der Pfad waren nicht das Problem, die Testdaten waren "zu alt")."""
    return datetime.now(UTC).isoformat()


@pytest.fixture(scope="function")
async def async_client():
    # LifespanManager startet den `anomaly_worker()`-Hintergrund-Task aus app/main.py.lifespan()
    # wirklich - reines `AsyncClient(transport=ASGITransport(app=app))` löst KEIN Startup-Event
    # aus, der Worker liefe in den Tests sonst nie (realer Fund, root-cause-omnimetric_engine-
    # asynchrone-race-condition-im-alert-test: selbst ein beliebig langes `sleep()` hätte hier
    # nichts geholfen, weil der Alert-erzeugende Task gar nicht existierte).
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_get_metric_stats_success(async_client: AsyncClient):
    """Testet, ob Statistiken nach dem Ingest korrekt abgerufen werden können."""
    payload = {"name": "test_metric", "value": 42.0, "timestamp": _fresh_timestamp()}
    response = await async_client.post("/api/v1/ingest", json=payload)
    assert response.status_code == 202

    # engine.ingest() (app/engine.py) trägt synchron im Request-Handler ein - kein Warten auf
    # den Hintergrund-Worker nötig, der befüllt nur den Alert-Pfad, nicht die Statistiken.
    response = await async_client.get("/api/v1/stats/test_metric")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_metric"
    assert data["count"] >= 1


@pytest.mark.asyncio
async def test_get_alerts_with_data(async_client: AsyncClient):
    """Testet, ob Anomalien korrekt erkannt und als Alerts bereitgestellt werden."""
    # Baseline aufbauen (anomaly_worker verlangt mindestens 10 Datenpunkte für den Z-Score).
    for _ in range(10):
        payload = {"name": "anomaly_metric", "value": 10.0, "timestamp": _fresh_timestamp()}
        res = await async_client.post("/api/v1/ingest", json=payload)
        assert res.status_code == 202

    # Anomalie einsenden (deutlicher Ausreißer, Z-Score > 3.0).
    payload = {"name": "anomaly_metric", "value": 1000.0, "timestamp": _fresh_timestamp()}
    res = await async_client.post("/api/v1/ingest", json=payload)
    assert res.status_code == 202

    # anomaly_worker (app/engine.py) läuft mit asyncio.sleep(5) zwischen den Durchläufen - der
    # Test pollt statt eines festen Sleeps, damit er nicht länger als nötig dauert, aber
    # mindestens einen vollen Zyklus abwartet.
    alert_found = False
    for _ in range(15):
        response = await async_client.get("/api/v1/alerts")
        assert response.status_code == 200
        data = response.json()
        if any(alert["metric_name"] == "anomaly_metric" for alert in data):
            alert_found = True
            break
        await asyncio.sleep(0.5)

    assert alert_found, "Erwarteter Alert für 'anomaly_metric' wurde nicht gefunden"
