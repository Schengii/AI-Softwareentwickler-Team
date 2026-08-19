# tests/test_job_search.py
import pytest

@pytest.mark.asyncio
async def test_search_fulltext(async_client, auth_header):
    params = {"q": "Software Engineer", "city": "Berlin", "page": 1, "limit": 10}
    resp = await async_client.get("/jobs", params=params, headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["items"], list)
    # Mindestens ein Treffer, wenn Test‑DB Seed‑Daten enthält
    # (Falls nicht, prüfen wir nur die Struktur)
    assert "total" in data


@pytest.mark.asyncio
async def test_search_no_results(async_client, auth_header):
    params = {"q": "UnmöglicherJobTitelXYZ", "city": "Nowhere"}
    resp = await async_client.get("/jobs", params=params, headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []


@pytest.mark.asyncio
async def test_job_detail_success(async_client, auth_header, create_job):
    """`create_job` ist ein Fixture (siehe unten) das einen Job in der DB anlegt."""
    job_id = create_job["id"]
    resp = await async_client.get(f"/jobs/{job_id}", headers=auth_header)
    assert resp.status_code == 200
    job = resp.json()
    assert job["id"] == job_id
    assert "description" in job


@pytest.mark.asyncio
async def test_job_detail_not_found(async_client, auth_header):
    resp = await async_client.get("/jobs/999999", headers=auth_header)
    assert resp.status_code == 404
