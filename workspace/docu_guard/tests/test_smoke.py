import pytest


@pytest.mark.asyncio
async def test_app_starts_and_health_ok(async_client):
    """Smoke-Test: Prüft, ob die App startet und die Root-Route erreichbar ist."""
    response = await async_client.get("/health")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_api_documents_list_empty(async_client):
    """Prüft, ob die Dokumentenliste initial leer ist."""
    response = await async_client.get("/api/v1/documents")
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_audit_logs_initial(async_client):
    """Prüft, ob die Audit-Logs initial leer sind."""
    response = await async_client.get("/api/v1/audit/logs")
    assert response.status_code == 200
    assert response.json() == []
