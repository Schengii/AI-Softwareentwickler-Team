import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import status

from app.main import app
from app.db import init_db, engine
from app.db import SQLModel


@pytest.fixture(scope="session")
def anyio_backend():
    # pytest-anyio braucht diese Fixture, um den zu nutzenden Backend (hier: asyncio) für
    # ALLE @pytest.mark.anyio-Tests der Session festzulegen - ohne sie schlägt jeder Zugriff
    # auf session-gescopte async-Fixtures mit "ScopeMismatch" fehl.
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
async def prepare_db():
    # Frische DB für Testlauf erzeugen
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)


@pytest.mark.anyio
async def test_create_note():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"content": "Erste Notiz"}
        resp = await client.post("/notes/", json=payload)
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["content"] == "Erste Notiz"
        assert "id" in data


@pytest.mark.anyio
async def test_list_notes():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Vorherige Notiz aus create‑Test existiert bereits
        resp = await client.get("/notes/")
        assert resp.status_code == status.HTTP_200_OK
        notes = resp.json()
        assert isinstance(notes, list)
        assert len(notes) >= 1  # mindestens die zuvor erstellte Notiz


@pytest.mark.anyio
async def test_delete_note():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Zuerst eine Notiz anlegen, um sie zu löschen
        create_resp = await client.post("/notes/", json={"content": "Zu löschen"})
        note_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/notes/{note_id}")
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT

        # Sicherstellen, dass die Notiz nicht mehr existiert
        get_resp = await client.get("/notes/")
        ids = [n["id"] for n in get_resp.json()]
        assert note_id not in ids
