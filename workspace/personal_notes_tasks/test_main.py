import pytest
from fastapi.testclient import TestClient
from main import app, notes, tasks

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    """Setzt den In-Memory-Speicher vor jedem Test zurück."""
    notes.clear()
    tasks.clear()

# --- Tests für Notizen ---

def test_create_note():
    response = client.post("/notes/", json={"title": "Test Note", "content": "Hello World"})
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Note"
    assert "id" in data

def test_get_notes():
    client.post("/notes/", json={"title": "Note 1", "content": "Content 1"})
    response = client.get("/notes/")
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_delete_note():
    note = client.post("/notes/", json={"title": "Delete Me", "content": "Content"}).json()
    response = client.delete(f"/notes/{note['id']}")
    assert response.status_code == 200
    assert len(client.get("/notes/").json()) == 0

# --- Tests für Aufgaben ---

def test_create_task():
    response = client.post("/tasks/", json={"title": "Test Task"})
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Task"
    assert data["completed"] is False

def test_get_tasks():
    client.post("/tasks/", json={"title": "Task 1"})
    response = client.get("/tasks/")
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_complete_task():
    task = client.post("/tasks/", json={"title": "Task to complete"}).json()
    response = client.put(f"/tasks/{task['id']}/complete")
    assert response.status_code == 200
    assert response.json()["completed"] is True

def test_complete_task_not_found():
    response = client.put("/tasks/non-existent-id/complete")
    assert response.status_code == 404
