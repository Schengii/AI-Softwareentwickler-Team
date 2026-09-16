"""
Tests für CloudPulse API-Routen (CRUD, Stats, Smoke-Tests, Validierung).
Verwendet synchronen FastAPI TestClient.
"""
import pytest
from fastapi.testclient import TestClient

# Robuster Import für app (main.py oder app.main)
try:
    from main import app
except ImportError:
    try:
        from app.main import app
    except ImportError:
        app = None


@pytest.fixture
def client():
    """Erstellt TestClient für FastAPI App."""
    if app is None:
        pytest.fail("FastAPI App 'app' konnte weder aus 'main' noch aus 'app.main' importiert werden.")
    return TestClient(app)


# ==========================================
# 1. Smoke Tests
# ==========================================

def test_app_starts_and_docs_available(client):
    """Smoke-Test: Prüft, ob die FastAPI-Instanz läuft und /docs erreichbar ist."""
    response = client.get("/docs")
    assert response.status_code == 200


def test_static_index_page(client):
    """Smoke-Test: Prüft, ob das Frontend unter / erreichbar ist."""
    response = client.get("/")
    assert response.status_code == 200
    assert "CloudPulse" in response.text or "text/html" in response.headers.get("content-type", "")


# ==========================================
# 2. Leere Datenbank & Initiale Stats
# ==========================================

def test_get_monitors_empty_initially(client):
    """Prüft, ob die Monitor-Liste initial (oder nach Bereinigung) ein JSON-Array zurückgibt."""
    response = client.get("/api/monitors")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_stats_initial_format(client):
    """Prüft, ob /api/stats die spezifizierten Pflichtfelder zurückliefert."""
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "up" in data
    assert "down" in data
    assert "avg_latency_ms" in data
    assert isinstance(data["total"], int)
    assert isinstance(data["up"], int)
    assert isinstance(data["down"], int)


# ==========================================
# 3. Monitor CRUD & Roundtrip
# ==========================================

def test_create_monitor_success_and_roundtrip(client):
    """
    Testet POST /api/monitors (Erstellung) und anschließenden GET Roundtrip.
    """
    payload = {
        "name": "Production API",
        "url": "https://httpbin.org/status/200",
        "interval_seconds": 30
    }
    create_res = client.post("/api/monitors", json=payload)
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert "id" in created_data
    monitor_id = created_data["id"]
    assert created_data["name"] == payload["name"]
    assert created_data["url"].rstrip("/") == payload["url"].rstrip("/")
    assert created_data["interval_seconds"] == payload["interval_seconds"]

    # Roundtrip: GET /api/monitors/{id}
    get_res = client.get(f"/api/monitors/{monitor_id}")
    assert get_res.status_code == 200
    fetched_data = get_res.json()
    assert fetched_data["id"] == monitor_id
    assert fetched_data["name"] == payload["name"]

    # Roundtrip: In der Gesamtliste enthalten
    list_res = client.get("/api/monitors")
    assert list_res.status_code == 200
    items = list_res.json()
    assert any(m["id"] == monitor_id for m in items)

    # Cleanup / Delete Test
    del_res = client.delete(f"/api/monitors/{monitor_id}")
    assert del_res.status_code == 204

    # Verifizieren, dass gelöscht
    not_found_res = client.get(f"/api/monitors/{monitor_id}")
    assert not_found_res.status_code == 404


def test_get_monitor_not_found(client):
    """Prüft GET /api/monitors/{id} für nicht existierende ID."""
    response = client.get("/api/monitors/99999999")
    assert response.status_code == 404


def test_delete_monitor_not_found(client):
    """Prüft DELETE /api/monitors/{id} für nicht existierende ID."""
    response = client.delete("/api/monitors/99999999")
    assert response.status_code == 404


# ==========================================
# 4. Validierung & Edge Cases
# ==========================================

def test_create_monitor_invalid_url(client):
    """Prüft, dass ungültige URLs mit HTTP 422 abgelehnt werden."""
    payload = {
        "name": "Invalid URL Service",
        "url": "not-a-valid-http-url",
        "interval_seconds": 60
    }
    response = client.post("/api/monitors", json=payload)
    assert response.status_code == 422


def test_create_monitor_missing_required_fields(client):
    """Prüft, dass fehlende Pflichtfelder (z. B. url) mit HTTP 422 abgelehnt werden."""
    payload = {
        "name": "Missing URL"
    }
    response = client.post("/api/monitors", json=payload)
    assert response.status_code == 422


def test_create_monitor_invalid_interval_type(client):
    """Prüft Typvalidierung für interval_seconds."""
    payload = {
        "name": "Bad Interval",
        "url": "https://example.com",
        "interval_seconds": "not-an-int"
    }
    response = client.post("/api/monitors", json=payload)
    assert response.status_code == 422
