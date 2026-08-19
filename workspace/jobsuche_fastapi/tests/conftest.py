# tests/conftest.py
import os
import asyncio
import httpx
import pytest
from dotenv import load_dotenv

load_dotenv(".env.test")

API_BASE = os.getenv("API_BASE_URL", "http://localhost:3000/api")
TEST_USER = {
    "email": "test_user@example.com",
    "password": "StrongP@ssw0rd!",
    "firstName": "Test",
    "lastName": "User"
}
ADMIN_USER = {
    "email": "admin@example.com",
    "password": "AdminP@ss123",
    "firstName": "Admin",
    "lastName": "User"
}


@pytest.fixture(scope="session")
def event_loop():
    """Ein einzelner Event‑Loop für alle async‑Tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def async_client():
    """Gemeinsamer httpx‑AsyncClient."""
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="session")
async def admin_token(async_client):
    """Login als Admin – erzeugt (falls nötig) den Admin‑User."""
    # 1. Admin ggf. registrieren
    await async_client.post("/auth/register", json=ADMIN_USER)
    # 2. Login
    resp = await async_client.post(
        "/auth/login",
        json={"email": ADMIN_USER["email"], "password": ADMIN_USER["password"]},
    )
    assert resp.status_code == 200
    return resp.json()["accessToken"]


@pytest.fixture(scope="session")
async def user_token(async_client):
    """Login als normaler Test‑User."""
    # Registrieren (idempotent – 409 wird ignoriert)
    await async_client.post("/auth/register", json=TEST_USER)
    # Login
    resp = await async_client.post(
        "/auth/login",
        json={"email": TEST_USER["email"], "password": TEST_USER["password"]},
    )
    assert resp.status_code == 200
    return resp.json()["accessToken"]


@pytest.fixture
def auth_header(user_token):
    """Header mit JWT für normale User‑Requests."""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def admin_header(admin_token):
    """Header mit JWT für Admin‑Requests."""
    return {"Authorization": f"Bearer {admin_token}"}
