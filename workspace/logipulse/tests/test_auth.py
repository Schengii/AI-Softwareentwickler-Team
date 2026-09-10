from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from src.config import get_settings

settings = get_settings()
from src.main import app

client = TestClient(app)

def create_test_token(user_id: str = "testuser", role: str = "user") -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30)
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_protected_route_without_token():
    response = client.get("/api/v1/protected")
    assert response.status_code == 401

def test_protected_route_with_valid_token():
    token = create_test_token()
    response = client.get(
        "/api/v1/protected",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["user_id"] == "testuser"

def test_admin_route_as_user():
    token = create_test_token(role="user")
    response = client.get(
        "/api/v1/admin",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403

def test_admin_route_as_admin():
    token = create_test_token(role="admin")
    response = client.get(
        "/api/v1/admin",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
