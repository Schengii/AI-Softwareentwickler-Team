from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_get_aggregation_success():
    # Warmup: Sende Metrik, damit Aggregator Daten hat
    client.post("/api/v1/metrics", json={"name": "cpu", "value": 50.0})
    
    response = client.get("/api/v1/metrics/aggregate?name=cpu&window_seconds=60")
    assert response.status_code == 200
    data = response.json()
    assert "metric_name" in data
    assert data["metric_name"] == "cpu"

def test_get_aggregation_empty():
    response = client.get("/api/v1/metrics/aggregate?name=nonexistent&window_seconds=60")
    assert response.status_code == 200
    assert response.json()["count"] == 0

def test_alert_lifecycle():
    # Erstellen
    rule = {
        "id": "test-rule-1",
        "name": "High CPU",
        "metric_name": "cpu",
        "aggregation": "avg",
        "condition": "gt",
        "threshold": 80.0,
        "enabled": True,
        "window_seconds": 60
    }
    response = client.post("/api/v1/alerts", json=rule)
    assert response.status_code == 201
    
    # Listen
    response = client.get("/api/v1/alerts")
    assert response.status_code == 200
    assert any(r["id"] == "test-rule-1" for r in response.json())
    
    # History
    response = client.get("/api/v1/alerts/history")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    
    # Löschen
    response = client.delete("/api/v1/alerts/test-rule-1")
    assert response.status_code == 200
    
    # Löschen Fehlerfall
    response = client.delete("/api/v1/alerts/nonexistent")
    assert response.status_code == 404
