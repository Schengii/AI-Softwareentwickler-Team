import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.job import JobStatus


@pytest.mark.asyncio
async def test_app_starts_and_health_ok():
    """Smoke-Test: Prüft, ob die App startet und erreichbar ist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Angenommen, es gibt eine Health-Route oder Root-Route
        response = await client.get("/health")
        assert response.status_code == 200

@pytest.mark.asyncio
async def test_create_job_roundtrip():
    """Testet das Erstellen eines Jobs und das anschließende Abrufen."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Payload basierend auf app/schemas/job.py (angenommen)
        payload = {
            "name": "test-job",
            "payload": {"data": "value"}
        }
        response = await client.post("/api/jobs", json=payload)
        assert response.status_code == 201
        
        job_id = response.json()["id"]
        
        # Lesen
        get_response = await client.get(f"/api/jobs/{job_id}")
        assert get_response.status_code == 200
        assert get_response.json()["name"] == "test-job"
        assert get_response.json()["status"] == JobStatus.PENDING.value
