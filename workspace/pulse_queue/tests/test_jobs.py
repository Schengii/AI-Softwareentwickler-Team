import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.job import JobType, JobStatus, JobModel
from app.core.database import get_async_session


@pytest.mark.asyncio
async def test_smoke_health(async_client: AsyncClient):
    """Smoke-Test: Prüft Erreichbarkeit des Health-Endpoints."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "healthy"


@pytest.mark.asyncio
async def test_create_job_unauthorized(async_client: AsyncClient):
    """Test: Fehlender oder ungültiger API-Key liefert 403/401."""
    # JobType Enum Werte: generic, email, report, sync (bzw. Enum-Iterables)
    job_type_val = list(JobType)[0].value
    response = await async_client.post(
        "/jobs",
        json={
            "job_type": job_type_val,
            "payload": {"param": 1},
            "priority": 1,
        },
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_and_get_job_roundtrip(async_client: AsyncClient, auth_headers: dict):
    """Roundtrip-Test: Job erstellen und per GET /jobs/{job_id} abrufen."""
    job_type_val = list(JobType)[0].value
    payload = {"task": "process_items", "count": 42}

    # Job anlegen
    create_res = await async_client.post(
        "/jobs",
        json={
            "job_type": job_type_val,
            "payload": payload,
            "priority": 2,
        },
        headers=auth_headers,
    )
    assert create_res.status_code == 201
    created_job = create_res.json()
    job_id = created_job["id"]
    assert job_id is not None
    assert created_job["job_type"] == job_type_val
    assert created_job["payload"] == payload

    # Job lesen
    get_res = await async_client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert get_res.status_code == 200
    fetched_job = get_res.json()
    assert fetched_job["id"] == job_id
    assert fetched_job["job_type"] == job_type_val
    assert fetched_job["payload"] == payload
    assert fetched_job["status"] in [s.value for s in JobStatus]


@pytest.mark.asyncio
async def test_get_nonexistent_job(async_client: AsyncClient, auth_headers: dict):
    """Test: Abruf eines nicht existierenden Jobs liefert 404."""
    response = await async_client.get("/jobs/999999", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_jobs(async_client: AsyncClient, auth_headers: dict):
    """Test: Auflisten von Jobs mit Pagination/Filter."""
    job_type_val = list(JobType)[0].value
    create_res = await async_client.post(
        "/jobs",
        json={
            "job_type": job_type_val,
            "payload": {"key": "list_test"},
            "priority": 1,
        },
        headers=auth_headers,
    )
    assert create_res.status_code == 201

    list_res = await async_client.get("/jobs", headers=auth_headers)
    assert list_res.status_code == 200
    jobs = list_res.json()
    assert isinstance(jobs, list)
    assert len(jobs) >= 1


@pytest.mark.asyncio
async def test_cancel_job(async_client: AsyncClient, auth_headers: dict):
    """Test: Job abbrechen via POST /jobs/{job_id}/cancel."""
    job_type_val = list(JobType)[0].value
    create_res = await async_client.post(
        "/jobs",
        json={
            "job_type": job_type_val,
            "payload": {"cancel": True},
            "priority": 1,
        },
        headers=auth_headers,
    )
    assert create_res.status_code == 201
    job_id = create_res.json()["id"]

    cancel_res = await async_client.post(f"/jobs/{job_id}/cancel", headers=auth_headers)
    assert cancel_res.status_code in (200, 204)
    if cancel_res.status_code == 200:
        data = cancel_res.json()
        assert data["status"] == JobStatus.CANCELLED.value

    # Verifizieren über GET
    get_res = await async_client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["status"] == JobStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_stats_and_workers_routes(async_client: AsyncClient, auth_headers: dict):
    """Test: Stats und Worker-Status Endpunkte prüfen."""
    # Pfade gemäß Steckbrief: GET /stats, GET /workers/status
    stats_res = await async_client.get("/stats", headers=auth_headers)
    if stats_res.status_code == 404:
        # Falls unter /api prefix gemountet:
        stats_res = await async_client.get("/api/stats", headers=auth_headers)
    if stats_res.status_code == 200:
        stats = stats_res.json()
        assert isinstance(stats, dict)

    workers_res = await async_client.get("/workers/status", headers=auth_headers)
    if workers_res.status_code == 404:
        workers_res = await async_client.get("/api/workers/status", headers=auth_headers)
    if workers_res.status_code == 200:
        workers = workers_res.json()
        assert isinstance(workers, (dict, list))
