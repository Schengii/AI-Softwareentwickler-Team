import os

import pytest
from fastapi.testclient import TestClient

from src.main import app

# Setze Umgebungsvariablen für Tests, falls nicht vorhanden
os.environ["SECRET_KEY"] = "super-secret-key-that-is-at-least-32-chars-long"
os.environ["API_KEY"] = "super-long-api-key-that-is-at-least-40-chars-long"

@pytest.fixture
def client():
    return TestClient(app)

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_login_success(client):
    response = client.post(
        "/token",
        data={"username": "admin", "password": "secret"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_login_failure(client):
    response = client.post(
        "/token",
        data={"username": "wrong", "password": "wrong"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Incorrect username or password"

def test_protected_route_without_token(client):
    response = client.get("/api/v1/protected")
    assert response.status_code == 401

def test_admin_route_as_admin(client):
    # Erst Token holen
    login_res = client.post("/token", data={"username": "admin", "password": "secret"})
    token = login_res.json()["access_token"]
    
    # Dann Admin-Route aufrufen
    response = client.get(
        "/api/v1/admin",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Hello admin"
