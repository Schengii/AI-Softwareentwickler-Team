# tests/test_deliveries_retry.py
"""
Tests für die Delivery‑Retry‑Route:
    POST /{delivery_id}/retry
Abgedeckte Fälle
    • Erfolgreicher Retry (Status 202, Rückgabe‑Message)
    • Fehlender Delivery‑Eintrag → 404
    • Ungültige UUID → 422 (FastAPI‑Validierung)
"""

import uuid

import pytest
from fastapi import status
from httpx import AsyncClient

# Der Smoke‑Test stellt sicher, dass die App startet.
# Wir importieren die FastAPI‑Instanz aus dem Projekt.
from app.main import app
from app.services.delivery import delivery_service
from app.db.session import get_db, async_session_factory

# ----------------------------------------------------------------------
# Test‑Setup: In‑Memory‑DB für alle Tests (Dependency‑Override)
# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def override_db():
    """
    Ersetzt die DB‑Dependency mit einer frischen In‑Memory‑Session.
    """
    async def _override():
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------
# Helper: Einen Delivery‑Datensatz anlegen
# ----------------------------------------------------------------------
async def _create_delivery(session, status_: str = "failed"):
    """Legt einen Delivery‑Eintrag an und gibt die ID zurück."""
    from app.models.delivery import Delivery  # lazy import nach DB‑Override

    delivery = Delivery(
        id=str(uuid.uuid4()),
        status=status_,
        payload={"foo": "bar"},
        attempts=0,
    )
    session.add(delivery)
    await session.commit()
    await session.refresh(delivery)
    return delivery.id


# ----------------------------------------------------------------------
# Smoke‑Test (bereits vorhanden, aber hier als Referenz)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_app_starts_and_health_ok():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == status.HTTP_200_OK


# ----------------------------------------------------------------------
# 1️⃣ Erfolgreicher Retry
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retry_success():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Delivery anlegen
        async with async_session_factory() as db:
            delivery_id = await _create_delivery(db)

        # Aufruf der Retry‑Route
        resp = await client.post(f"/{delivery_id}/retry")
        assert resp.status_code == status.HTTP_202_ACCEPTED
        json = resp.json()
        assert json["message"] == "Retry scheduled"
        # Service‑Aufruf prüfen (Mock‑frei – wir prüfen den DB‑Zustand)
        async with async_session_factory() as db:
            from app.models.delivery import Delivery

            db_delivery = await db.get(Delivery, delivery_id)
            assert db_delivery.attempts == 1
            assert db_delivery.status == "queued"


# ----------------------------------------------------------------------
# 2️⃣ Delivery nicht gefunden → 404
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retry_not_found():
    async with AsyncClient(app=app, base_url="http://test") as client:
        non_existent = str(uuid.uuid4())
        resp = await client.post(f"/{non_existent}/retry")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()["detail"] == "Delivery not found"


# ----------------------------------------------------------------------
# 3️⃣ Ungültige UUID → 422 (FastAPI‑Validierung)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retry_invalid_uuid():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/invalid-uuid/retry")
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
