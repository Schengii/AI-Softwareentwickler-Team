"""Unit- und Integrations-Testsuite für ChronosPulse."""
from __future__ import annotations

import time
import pytest
from httpx import AsyncClient

from app.main import AnomalyEvent, MetricRecord, WebhookRecord
from app.ml.anomaly_detector import AnomalyDetector


# --- 1. Smoke Tests ---
@pytest.mark.asyncio
async def test_smoke_health_check(client: AsyncClient):
    """Smoke-Test: Systemstart und Health-Endpoint /health verifizieren."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "uptime_seconds" in data


# --- 2. Metriken: Ingestion & Roundtrips ---
@pytest.mark.asyncio
async def test_metrics_ingest_and_read_roundtrip(client: AsyncClient):
    """Prüft POST /api/v1/metrics und verifiziert die Persistenz via GET."""
    payload = {
        "metric_name": "http_request_duration_ms",
        "value": 142.5,
        "service": "checkout-service",
        "tags": {"env": "production", "region": "eu-central-1"}
    }

    # 1. Metrik einspeisen (Write)
    create_res = await client.post("/api/v1/metrics", json=payload)
    assert create_res.status_code == 201
    created_record = MetricRecord.model_validate(create_res.json())
    assert created_record.metric_name == payload["metric_name"]
    assert created_record.service == payload["service"]

    # 2. Metriken abfragen (Read-Roundtrip mit Filter)
    get_res = await client.get("/api/v1/metrics?service=checkout-service")
    assert get_res.status_code == 200
    metrics_list = [MetricRecord.model_validate(m) for m in get_res.json()]
    assert len(metrics_list) == 1
    assert metrics_list[0].id == created_record.id
    assert metrics_list[0].value == 142.5


@pytest.mark.asyncio
async def test_metrics_filtering_by_name_and_limit(client: AsyncClient):
    """Prüft Filterung nach metric_name und Limit-Beschränkung."""
    for i in range(5):
        await client.post("/api/v1/metrics", json={
            "metric_name": "cpu_utilization",
            "value": float(20 + i),
            "service": "auth-service"
        })

    await client.post("/api/v1/metrics", json={
        "metric_name": "memory_utilization",
        "value": 55.0,
        "service": "auth-service"
    })

    # Filter nach metric_name
    res = await client.get("/api/v1/metrics?metric_name=cpu_utilization&limit=3")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 3
    assert all(item["metric_name"] == "cpu_utilization" for item in data)


# --- 3. Anomalieerkennung & Incident Management ---
@pytest.mark.asyncio
async def test_predictive_anomaly_detection_with_warmup(client: AsyncClient):
    """Warmup-Phase einhalten und anschließenden Latenz-Spike detektieren."""
    service_name = "payment-gateway"
    metric = "latency_ms"

    # Warmup-Phase: 10 gleichmäßige Datenpunkte einspeisen (Baseline 100ms)
    for _ in range(10):
        res = await client.post("/api/v1/metrics", json={
            "metric_name": metric,
            "value": 100.0,
            "service": service_name
        })
        assert res.status_code == 201

    # Anomalien prüfen: Noch keine vorhanden
    anomalies_before = await client.get(f"/api/v1/anomalies?service={service_name}")
    assert anomalies_before.status_code == 200
    assert len(anomalies_before.json()) == 0

    # Extremen Spike einspeisen (10.000ms statt 100ms)
    spike_res = await client.post("/api/v1/metrics", json={
        "metric_name": metric,
        "value": 10000.0,
        "service": service_name
    })
    assert spike_res.status_code == 201

    # Anomalie-Prüfung: Automatische Incident-Erstellung
    anomalies_after = await client.get(f"/api/v1/anomalies?service={service_name}")
    assert anomalies_after.status_code == 200
    anomalies = [AnomalyEvent.model_validate(a) for a in anomalies_after.json()]
    assert len(anomalies) >= 1
    detected = anomalies[0]
    assert detected.service == service_name
    assert detected.actual_value == 10000.0
    assert detected.severity in ["warning", "critical"]
    assert detected.acknowledged is False


@pytest.mark.asyncio
async def test_anomaly_acknowledge_lifecycle(client: AsyncClient):
    """Testet Erstellung, Abfrage und Acknowledgment einer Anomalie."""
    # 1. Anomalie manuell anlegen
    anomaly_data = {
        "metric_name": "error_rate",
        "service": "order-service",
        "expected_value": 0.01,
        "actual_value": 0.35,
        "z_score": 6.2,
        "severity": "critical",
        "description": "Kritischer Anstieg der Fehlerrate"
    }
    create_res = await client.post("/api/v1/anomalies", json=anomaly_data)
    assert create_res.status_code == 201
    anomaly = AnomalyEvent.model_validate(create_res.json())
    anomaly_id = anomaly.id

    # 2. Acknowledge (PATCH)
    patch_res = await client.patch(f"/api/v1/anomalies/{anomaly_id}/acknowledge")
    assert patch_res.status_code == 200
    ack_data = AnomalyEvent.model_validate(patch_res.json())
    assert ack_data.id == anomaly_id
    assert ack_data.acknowledged is True

    # 3. Nicht existente ID prüfen
    err_res = await client.patch("/api/v1/anomalies/non-existent-id/acknowledge")
    assert err_res.status_code == 404


# --- 4. Webhooks Endpoints ---
@pytest.mark.asyncio
async def test_webhook_ingest_and_list_roundtrip(client: AsyncClient):
    """Prüft Ingestion externer Alarme und List-Endpunkt."""
    webhook_payload = {
        "event_type": "alert.firing",
        "source": "prometheus-alertmanager",
        "payload": {"alertname": "HighDiskUsage", "instance": "node-01"},
        "secret": "pulse-secret-xyz"
    }

    create_res = await client.post("/api/v1/webhooks", json=webhook_payload)
    assert create_res.status_code in [200, 201]
    created_wh = WebhookRecord.model_validate(create_res.json())
    assert created_wh.source == webhook_payload["source"]

    list_res = await client.get("/api/v1/webhooks")
    assert list_res.status_code == 200
    items = [WebhookRecord.model_validate(w) for w in list_res.json()]
    assert any(w.id == created_wh.id for w in items)


# --- 5. Unit-Test: AnomalyDetector (Algorithmus & Kaltstart) ---
def test_anomaly_detector_cold_start_and_drift():
    """Unit-Test für den statistischen Detektor ohne API-Overhead."""
    detector = AnomalyDetector()
    service = "user-auth"
    metric = "login_latency"

    # 1. Kaltstart: Erste 3 Werte (noch keine Baseline-Standardabweichung)
    for _ in range(3):
        is_anom, z, _ = detector.update_and_detect(service, metric, 50.0)
        assert is_anom is False

    # 2. Stabilisierung
    for _ in range(15):
        detector.update_and_detect(service, metric, 50.0)

    # 3. Massiver Ausreißer (> 4 Sigma)
    is_anomaly, z_score, expected = detector.update_and_detect(service, metric, 500.0)
    assert is_anomaly is True
    assert z_score > 3.0
    assert abs(expected - 50.0) < 10.0
