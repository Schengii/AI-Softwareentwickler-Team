# tests/test_profile.py
import pytest
import httpx
import pathlib

@pytest.mark.asyncio
async def test_get_own_profile(async_client, auth_header):
    resp = await async_client.get("/users/me", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test_user@example.com"


@pytest.mark.asyncio
async def test_update_profile(async_client, auth_header):
    update = {"city": "Berlin", "desiredSalary": 65000, "skills": ["Python", "FastAPI"]}
    resp = await async_client.put("/users/me", json=update, headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == "Berlin"
    assert data["desiredSalary"] == 65000
    assert "Python" in data["skills"]


@pytest.mark.asyncio
async def test_cv_upload_success(async_client, auth_header, tmp_path):
    # Erstelle eine kleine PDF‑Datei (max 5 MB)
    pdf_path = tmp_path / "cv.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%TestCV\n%%EOF")
    files = {"file": ("cv.pdf", pdf_path.open("rb"), "application/pdf")}
    resp = await async_client.post("/users/me/cv", files=files, headers=auth_header)
    assert resp.status_code == 201
    data = resp.json()
    assert data["cvUrl"].endswith(".pdf")


@pytest.mark.asyncio
async def test_cv_upload_too_large(async_client, auth_header, tmp_path):
    # 6 MB Dummy‑File → sollte 413 zurückgeben
    big_file = tmp_path / "big.pdf"
    big_file.write_bytes(b"0" * 6 * 1024 * 1024)
    files = {"file": ("big.pdf", big_file.open("rb"), "application/pdf")}
    resp = await async_client.post("/users/me/cv", files=files, headers=auth_header)
    assert resp.status_code == 413
