import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_list_dlq_empty():
    """Testet, dass die DLQ anfangs leer ist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/dlq")
        assert response.status_code == 200
        assert response.json() == []

@pytest.mark.asyncio
async def test_list_jobs_empty():
    """Testet, dass die Job-Liste anfangs leer ist."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/jobs")
        assert response.status_code == 200
        assert response.json() == []
