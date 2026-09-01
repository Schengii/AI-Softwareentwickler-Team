import pytest
from fastapi.testclient import TestClient
from app.main import app
import uuid

client = TestClient(app)

def test_upload_file_success():
    """Testet den erfolgreichen Datei-Upload."""
    files = {"file": ("test.txt", b"hello world", "text/plain")}
    response = client.post("/api/v1/files/upload", files=files, params={"tags": "test,demo"})
    
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "test.txt"
    assert "test" in data["tags"]
    assert "demo" in data["tags"]
    assert "id" in data

def test_create_share_link_success():
    """Testet die Erstellung eines Share-Links."""
    file_id = str(uuid.uuid4())
    payload = {"expires_in_hours": 1}
    response = client.post(f"/api/v1/files/{file_id}/link", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert "download_url" in data
    assert "expires_at" in data

def test_get_tags_success():
    """Testet den Abruf der Tags."""
    response = client.get("/api/v1/tags")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert "work" in response.json()
