# tests/test_auth.py
import pytest
import httpx

@pytest.mark.asyncio
async def test_register_success(async_client):
    payload = {
        "email": "new_user@example.com",
        "password": "ValidP@ss123",
        "firstName": "New",
        "lastName": "User"
    }
    resp = await async_client.post("/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "accessToken" in data
    assert data["user"]["email"] == payload["email"]


@pytest.mark.asyncio
async def test_register_duplicate_email(async_client):
    # Erstes Mal registrieren (sollte 201 geben)
    payload = {
        "email": "dup_user@example.com",
        "password": "ValidP@ss123",
        "firstName": "Dup",
        "lastName": "User"
    }
    await async_client.post("/auth/register", json=payload)

    # Zweites Mal -> 400 (oder 409 je nach Implementation)
    resp = await async_client.post("/auth/register", json=payload)
    assert resp.status_code in (400, 409)
    assert "already exists" in resp.text.lower()


@pytest.mark.asyncio
async def test_login_success(async_client):
    payload = {"email": "new_user@example.com", "password": "ValidP@ss123"}
    resp = await async_client.post("/auth/login", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "accessToken" in data


@pytest.mark.asyncio
async def test_login_invalid_password(async_client):
    payload = {"email": "new_user@example.com", "password": "WrongPass"}
    resp = await async_client.post("/auth/login", json=payload)
    assert resp.status_code == 401
    assert "invalid credentials" in resp.text.lower()


@pytest.mark.asyncio
async def test_password_reset_request_success(async_client):
    resp = await async_client.post(
        "/auth/password-reset",
        json={"email": "new_user@example.com"},
    )
    assert resp.status_code == 200
    # Wir prüfen nur den Status; das Mail‑Queue‑Mocking erfolgt im Backend‑Test
