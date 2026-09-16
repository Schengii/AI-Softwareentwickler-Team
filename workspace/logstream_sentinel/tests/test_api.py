from fastapi.testclient import TestClient

from main import app


# Smoke-Test: App-Start und Health-Check
def test_app_starts_and_health_ok():
    client = TestClient(app)
    # Da kein expliziter Health-Endpoint definiert wurde, prüfen wir die Root-Route
    response = client.get("/")
    assert response.status_code == 200

# Test der Log-Ingestion
def test_log_ingestion():
    client = TestClient(app)
    payload = {
        "service_name": "test-service",
        "level": "INFO",
        "message": "Test log message",
        "metadata": {"key": "value"},
        "timestamp": "2026-09-16T12:00:00Z"
    }
    response = client.post("/api/logs", json=payload)
    assert response.status_code in [200, 201]

# Test der Log-Filterung
def test_get_logs_filter():
    client = TestClient(app)
    response = client.get("/api/logs?level=INFO")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

# Test der Stats-Abfrage
def test_get_stats():
    client = TestClient(app)
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "log_rate_per_minute" in data
    assert "error_rate_percent" in data

# Test der Incident-Abfrage
def test_get_incidents():
    client = TestClient(app)
    response = client.get("/api/incidents")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

# Test der Log-Bereinigung
def test_delete_logs():
    client = TestClient(app)
    response = client.delete("/api/logs?retention_minutes=60")
    assert response.status_code == 200
