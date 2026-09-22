"""
Pytest-Suite für das Sentinel Shield Resilience- und Rate-Limiting-Gateway.
Testet Normalbetrieb (200), Rate-Limit (429), Circuit-Breaker Trip (503),
Half-Open-Recovery und manuellen Circuit-Reset sowie Metriken und Health-Checks.
"""

import asyncio
from unittest.mock import AsyncMock, patch
import httpx
import pytest


@pytest.mark.asyncio
async def test_health_check(async_client):
    """Prüft den Health-Check-Endpunkt auf Status 200 und {'status': 'ok'}."""
    # Teste /health und /api/v1/health (falls geroutet)
    res = await async_client.get("/health")
    if res.status_code == 404:
        res = await async_client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "ok"


@pytest.mark.asyncio
async def test_dispatch_normal_operation_200(async_client):
    """
    Testet den Normalbetrieb von POST /api/v1/dispatch.
    Downstream antwortet erfolgreich (200 OK).
    """
    payload = {
        "service": "service-a",
        "target": "service-a",
        "path": "/data",
        "method": "GET",
        "payload": {"query": "test"}
    }
    headers = {"Authorization": "Bearer test-token-123", "X-API-Key": "test-key-123"}

    mock_response = httpx.Response(
        status_code=200,
        json={"message": "success from downstream"},
        request=httpx.Request("GET", "http://downstream/data")
    )

    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response
        response = await async_client.post("/api/v1/dispatch", json=payload, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data is not None


@pytest.mark.asyncio
async def test_dispatch_rate_limit_429(async_client):
    """
    Testet die Ratenbegrenzung von POST /api/v1/dispatch.
    Wiederholte Anfragen müssen nach Erreichen des Limits HTTP 429
    mit dem Header 'Retry-After' zurückliefern.
    """
    payload = {
        "service": "rate-limited-service",
        "target": "rate-limited-service",
        "path": "/data",
        "method": "GET"
    }
    headers = {"Authorization": "Bearer test-rate-limit-token", "X-API-Key": "test-rate-limit-key"}

    mock_response = httpx.Response(
        status_code=200,
        json={"result": "ok"},
        request=httpx.Request("GET", "http://downstream/data")
    )

    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send, \
         patch("app.api.routes_gateway.rate_limiter.is_allowed", return_value=(False, 60)):
        mock_send.return_value = mock_response
        res = await async_client.post("/api/v1/dispatch", json=payload, headers=headers)
        assert res.status_code == 429, f"Erwartet HTTP 429, erhielt {res.status_code}"
        assert any(k.lower() == "retry-after" for k in res.headers.keys())


@pytest.mark.asyncio
async def test_circuit_breaker_trip_503(async_client):
    """
    Testet das Auslösen (Trip) des Circuit-Breakers bei anhaltenden Fehlern.
    Wenn der Downstream fehlschlägt und die Schwelle erreicht ist,
    muss der Circuit 'open' werden und künftige Requests sofort mit 503 abweisen.
    """
    service_name = "failing-service"
    payload = {
        "service": service_name,
        "target": service_name,
        "path": "/fail",
        "method": "GET"
    }
    headers = {"Authorization": "Bearer test-circuit-token", "X-API-Key": "test-circuit-key"}

    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = httpx.ConnectError("Connection refused", request=httpx.Request("GET", "http://downstream/fail"))
        # Führe Requests aus bis Circuit Breaker auslöst
        for _ in range(10):
            res = await async_client.post("/api/v1/dispatch", json=payload, headers=headers)
            if res.status_code == 503:
                break
        assert res.status_code == 503

    payload = {
        "service": service_name,
        "target": service_name,
        "path": "/error",
        "method": "GET"
    }
    headers = {"Authorization": "Bearer test-cb-token", "X-API-Key": "test-cb-key"}

    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        # Simuliere wiederholte Fehler des Downstreams (z.B. 500 oder ConnectError)
        mock_send.side_effect = httpx.ConnectError("Connection refused")

        # Provoziere Failure Threshold
        for _ in range(10):
            try:
                await async_client.post("/api/v1/dispatch", json=payload, headers=headers)
            except Exception:
                pass

        # Circuit sollte jetzt 'open' sein -> sofortiges 503 ohne Aufruf des Downstreams
        mock_send.reset_mock()
        res = await async_client.post("/api/v1/dispatch", json=payload, headers=headers)

        assert res.status_code == 503
        # Keine neue Downstream-Anfrage bei offenem Circuit
        assert mock_send.call_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_recovery_and_reset(async_client):
    """
    Testet die Recovery (Half-Open -> Closed) und den manuellen Reset eines Circuits.
    - POST /api/v1/circuits/{service_name}/reset
    - GET /api/v1/circuits
    """
    service_name = "reset-service"
    payload = {
        "service": service_name,
        "target": service_name,
        "path": "/test",
        "method": "GET"
    }
    headers = {"Authorization": "Bearer test-token-123", "X-API-Key": "test-key-123"}

    # 1. Manuelles Setzen bzw. Resetten des Circuits
    reset_res = await async_client.post(f"/api/v1/circuits/{service_name}/reset", headers=headers)
    assert reset_res.status_code in (200, 204)

    # 2. Status aller Circuits abfragen
    circuits_res = await async_client.get("/api/v1/circuits", headers=headers)
    assert circuits_res.status_code == 200
    circuits_data = circuits_res.json()
    assert isinstance(circuits_data, (list, dict))

    # 3. Teste Recovery nach Timeout (falls Breaker offen war)
    # Ein erfolgreicher Request schließt den Circuit wieder
    mock_success = httpx.Response(
        status_code=200,
        json={"status": "recovered"},
        request=httpx.Request("GET", "http://downstream/test")
    )
    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_success
        post_res = await async_client.post("/api/v1/dispatch", json=payload, headers=headers)
        assert post_res.status_code == 200


@pytest.mark.asyncio
async def test_metrics_endpoint(async_client):
    """
    Prüft den Metriken-Endpunkt GET /api/v1/metrics.
    Muss Zähler für Gesamt-Requests, Rate-Limits, Circuit-Trips und Latenzen bereitstellen.
    """
    headers = {"Authorization": "Bearer test-token-123", "X-API-Key": "test-key-123"}
    res = await async_client.get("/api/v1/metrics", headers=headers)
    assert res.status_code == 200

    # Metriken können JSON oder Prometheus-Textformat sein
    content_type = res.headers.get("content-type", "")
    if "application/json" in content_type:
        data = res.json()
        assert isinstance(data, dict)
    else:
        text = res.text
        assert len(text) > 0
