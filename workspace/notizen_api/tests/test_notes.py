import pytest
from fastapi.testclient import TestClient
from app.main import app, notes_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_db():
    notes_db.clear()

def test_create_note():
    response = client.post("/notes/", json={"title": "Test", "content": "Content"})
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test"
    assert "id" in data

def test_list_notes():
    client.post("/notes/", json={"title": "T1", "content": "C1"})
    response = client.get("/notes/")
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_update_note():
    create_res = client.post("/notes/", json={"title": "Old", "content": "Old"})
    note_id = create_res.json()["id"]
    
    update_res = client.put(f"/notes/{note_id}", json={"title": "New", "content": "New"})
    assert update_res.status_code == 200
    assert update_res.json()["title"] == "New"

def test_delete_note():
    create_res = client.post("/notes/", json={"title": "Del", "content": "Del"})
    note_id = create_res.json()["id"]
    
    del_res = client.delete(f"/notes/{note_id}")
    assert del_res.status_code == 200
    
    get_res = client.get("/notes/")
    assert len(get_res.json()) == 0

def test_delete_nonexistent_note():
    response = client.delete("/notes/nonexistent")
    assert response.status_code == 404
