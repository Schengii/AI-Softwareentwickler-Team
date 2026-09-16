from fastapi.testclient import TestClient

from app.main import BucketResponse, EventResponse, StatsResponse, app

client = TestClient(app)


def test_app_starts_and_health_ok():
    """Smoke-Test: Prüft, ob die App startet und Health-Endpunkt erreichbar ist."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"


def test_create_and_get_bucket():
    """Roundtrip: Bucket erstellen und abrufen."""
    create_payload = {"name": "Test-Bucket", "target_url": "https://httpbin.org/post"}
    res = client.post("/api/buckets", json=create_payload)
    assert res.status_code == 201
    created = res.json()
    bucket_model = BucketResponse.model_validate(created)
    assert bucket_model.name == "Test-Bucket"
    bucket_id = bucket_model.id

    list_res = client.get("/api/buckets")
    assert list_res.status_code == 200
    buckets = list_res.json()
    assert any(b["id"] == bucket_id for b in buckets)

    # Aufräumen
    del_res = client.delete(f"/api/buckets/{bucket_id}")
    assert del_res.status_code == 200


def test_ingest_event_and_list():
    """Event über Ingestion senden und im Bucket prüfen."""
    b_res = client.post("/api/buckets", json={"name": "Ingest-Test"})
    assert b_res.status_code == 201
    bucket_id = b_res.json()["id"]

    ingest_res = client.post(f"/hook/{bucket_id}", json={"test_key": "test_value"})
    assert ingest_res.status_code == 200
    ingest_data = ingest_res.json()
    assert ingest_data.get("status") == "received"

    events_res = client.get(f"/api/buckets/{bucket_id}/events")
    assert events_res.status_code == 200
    events = events_res.json()
    assert len(events) >= 1
    EventResponse.model_validate(events[0])

    client.delete(f"/api/buckets/{bucket_id}")


def test_stats():
    """Statistiken über /api/stats prüfen."""
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    # Pydantic Typ-Validierung gegen StatsResponse
    stats = StatsResponse.model_validate(data)
    assert isinstance(stats.total_buckets, int)
    assert isinstance(stats.total_events, int)
    assert isinstance(stats.forwarded_success, int)
    assert isinstance(stats.forwarded_failed, int)
    assert "success_rate_percent" in data or "success_rate" in data
