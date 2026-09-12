"""Integrationstests für die FastAPI-Endpunkte von HookSentinel."""

import asyncio
from httpx import ASGITransport, AsyncClient

from app.db import close_db, init_db
from app.main import app


def test_get_stats():
    """Prüft, ob der /api/v1/stats Endpunkt Kennzahlen liefert."""
    async def _run():
        await init_db()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/stats")
        await close_db()
        assert response.status_code == 200
        data = response.json()
        assert "events_by_status" in data
        assert "dlq_count" in data
        assert "source_count" in data

    asyncio.run(_run())


def test_get_events():
    """Prüft, ob die Event-Historie abrufbar ist."""
    async def _run():
        await init_db()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/events")
        await close_db()
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    asyncio.run(_run())


def test_get_dlq():
    """Prüft, ob die Dead-Letter-Queue Liste abrufbar ist."""
    async def _run():
        await init_db()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/dlq")
        await close_db()
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    asyncio.run(_run())


def test_webhook_unknown_source():
    """Ungültige Webhook-Quelle muss mit 400 Bad Request quittiert werden."""
    async def _run():
        await init_db()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/webhook/non-existent-source",
                json={"event": "ping"},
            )
        await close_db()
        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "unknown_source"

    asyncio.run(_run())
