"""
Smoke- und Integrationstests für den notecatcher-Service.

Strategie:
- Smoke-Test zuerst: App-Start + Health-Route
- Dann CRUD-Szenarien: POST, GET-Liste, GET-Einzel, 404, Edge Cases
- Isolation: Vor jedem Test wird der In-Memory-Speicher zurückgesetzt
"""
import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app


@pytest.fixture(autouse=True)
def reset_notes():
    """Setzt den In-Memory-Speicher vor jedem Test zurück (Isolation)."""
    app_main._notes.clear()
    app_main._next_id = 1
    yield
    app_main._notes.clear()
    app_main._next_id = 1


@pytest.fixture
def client():
    """TestClient für die FastAPI-App."""
    return TestClient(app)


# ─────────────────────────────────────────────
# Smoke-Test
# ─────────────────────────────────────────────

def test_app_starts_and_health_ok(client):
    """Smoke-Test: App startet und Health-Route antwortet 200."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ─────────────────────────────────────────────
# POST /notes
# ─────────────────────────────────────────────

def test_create_note_returns_201(client):
    """POST /notes mit gültigem Payload liefert 201 und die Notiz mit ID."""
    response = client.post("/notes", json={"text": "Erste Notiz"})
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == 1
    assert data["text"] == "Erste Notiz"
    assert data["tag"] is None


def test_create_note_with_tag(client):
    """POST /notes mit optionalem tag-Feld speichert das Tag."""
    response = client.post("/notes", json={"text": "Mit Tag", "tag": "wichtig"})
    assert response.status_code == 201
    data = response.json()
    assert data["tag"] == "wichtig"


def test_create_note_increments_id(client):
    """Jede neue Notiz erhält eine eindeutige, aufsteigende ID."""
    r1 = client.post("/notes", json={"text": "A"})
    r2 = client.post("/notes", json={"text": "B"})
    assert r1.json()["id"] == 1
    assert r2.json()["id"] == 2


def test_create_note_empty_text_rejected(client):
    """Leerer Text wird von Pydantic (min_length=1) mit 422 abgewiesen."""
    response = client.post("/notes", json={"text": ""})
    assert response.status_code == 422


def test_create_note_missing_text_rejected(client):
    """Fehlendes Pflichtfeld 'text' wird mit 422 abgewiesen."""
    response = client.post("/notes", json={})
    assert response.status_code == 422


def test_create_note_invalid_json_rejected(client):
    """Ungültiges JSON wird mit 422 abgewiesen."""
    response = client.post("/notes", content=b"not-json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422


# ─────────────────────────────────────────────
# GET /notes
# ─────────────────────────────────────────────

def test_list_notes_empty(client):
    """Ohne Notizen liefert GET /notes eine leere Liste."""
    response = client.get("/notes")
    assert response.status_code == 200
    assert response.json() == []


def test_list_notes_with_items(client):
    """GET /notes liefert alle angelegten Notizen."""
    client.post("/notes", json={"text": "Notiz 1"})
    client.post("/notes", json={"text": "Notiz 2"})
    response = client.get("/notes")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["text"] == "Notiz 1"
    assert data[1]["text"] == "Notiz 2"


# ─────────────────────────────────────────────
# GET /notes/{id}
# ─────────────────────────────────────────────

def test_get_note_by_id(client):
    """GET /notes/{id} liefert die korrekte Notiz."""
    client.post("/notes", json={"text": "Notiz 1"})
    response = client.get("/notes/1")
    assert response.status_code == 200
    assert response.json()["text"] == "Notiz 1"


def test_get_note_not_found(client):
    """GET /notes/{id} mit unbekannter ID liefert 404."""
    response = client.get("/notes/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Note not found"
