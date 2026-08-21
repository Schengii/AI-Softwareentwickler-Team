import pytest
from fastapi.testclient import TestClient
from app.main import app, contacts

client = TestClient(app)

def setup_function():
    contacts.clear()

def test_create_contact():
    response = client.post("/contacts", json={"name": "Max Mustermann", "email": "max@example.com", "phone": "12345"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Max Mustermann"
    assert "id" in data

def test_get_contacts():
    client.post("/contacts", json={"name": "A", "email": "a@a.com"})
    response = client.get("/contacts")
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_get_contact_not_found():
    response = client.get("/contacts/999")
    assert response.status_code == 404

def test_update_contact():
    # Erstelle Kontakt und extrahiere ID
    post_response = client.post("/contacts", json={"name": "A", "email": "a@a.com"})
    contact_id = post_response.json()["id"]
    
    # Update mit dynamischer ID
    response = client.put(f"/contacts/{contact_id}", json={"name": "B", "email": "b@b.com"})
    assert response.status_code == 200
    assert response.json()["name"] == "B"

def test_delete_contact():
    # Erstelle Kontakt und extrahiere ID
    post_response = client.post("/contacts", json={"name": "A", "email": "a@a.com"})
    contact_id = post_response.json()["id"]
    
    # Lösche mit dynamischer ID
    response = client.delete(f"/contacts/{contact_id}")
    assert response.status_code == 204
    
    # Prüfe ob gelöscht
    assert client.get(f"/contacts/{contact_id}").status_code == 404
