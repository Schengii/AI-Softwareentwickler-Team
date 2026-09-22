# tests/test_events_publish.py
"""
Tests für die Event‑Publish‑Route:
    POST /events/publish
Abgedeckte Fälle
    • Erfolgreiches Publizieren (Status 202, matched_count)
    • Keine Subscriptions → matched_count 0
    • Fehlende Pflichtfelder → 422
"""

import pytest
from fastapi import status
from httpx import AsyncClient

from app.main import app
from app.db.session import get_db, async_session_factory
from app.models.webhook import Subscription


# ----------------------------------------------------------------------
# DB‑Override (wie im Delivery‑Test)
# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def override_db():
    async def _override():
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------
# Helper: Subscription anlegen
# ----------------------------------------------------------------------
async def _create_subscription(session, event_id: str = "order.created"):
    sub = Subscription(
        id="sub-1",
        event_id=event_id,
        target_url="http://example.com/webhook",
        secret="s3cr3t",
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub.id


# ----------------------------------------------------------------------
# 1️⃣ Erfolgreiches Publizieren (eine Subscription wird gefunden)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_publish_event_success():
    async with AsyncClient(app=app, base_url="http://test") as client:
        async with async_session_factory() as db:
            await _create_subscription(db)

        payload = {"order_id": 123, "amount": 9.99}
        resp = await client.post(
            "/events/publish",
            json={"event_id": "order.created", "payload": payload},
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["matched_count"] == 1
        assert "Event published" in data["message"]


# ----------------------------------------------------------------------
# 2️⃣ Keine Subscriptions → matched_count 0
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_publish_event_no_match():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Keine Subscription in DB
        resp = await client.post(
            "/events/publish",
            json={"event_id": "nonexistent.event", "payload": {}},
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["matched_count"] == 0
        assert "Event published" in data["message"]


# ----------------------------------------------------------------------
# 3️⃣ Validierungsfehler (fehlendes event_id) → 422
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_publish_event_invalid():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/events/publish",
            json={"payload": {"foo": "bar"}},  # event_id fehlt
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
