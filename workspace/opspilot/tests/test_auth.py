from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router

app = FastAPI()
app.include_router(auth_router, prefix="/api/v1/auth")

client = TestClient(app)

def test_login_success():
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_login_failure():
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"

def test_login_invalid_user():
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "unknown", "password": "admin"},
    )
    assert response.status_code == 401
