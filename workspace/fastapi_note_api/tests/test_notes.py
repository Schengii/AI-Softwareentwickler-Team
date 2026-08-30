import pytest
from httpx import AsyncClient
from fastapi import status

from app.main import app
from app.db import engine


@pytest.fixture(scope="session", autouse=True)
async def prepare_db():
    # Frische DB für Testlauf erzeugen
    async with engine.begin() as conn:
        await conn.run_sync(app.db.SQLModel.metadata.drop_all)
        await conn.run_sync(app.db.SQLModel.metadata.create_all)


@pytest.mark.anyio
async def test_create_note():
    async with AsyncClient(app=app, base_url="http://test") as client:
        payload = {"content": "Erste Notiz"}
        resp = await client.post("/notes", json=payload)
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["content"] == "Erste Notiz"
        assert "id" in data


@pytest.mark.anyio
async def test_list_notes():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Vorherige Notiz aus create‑Test existiert bereits
        resp = await client.get("/notes")
        assert resp.status_code == status.HTTP_200_OK
        notes = resp.json()
        assert isinstance(notes, list)
        assert len(notes) >= 1  # mindestens die zuvor erstellte Notiz


@pytest.mark.anyio
async def test_delete_note():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Zuerst eine Notiz anlegen, um sie zu löschen
        create_resp = await client.post("/notes", json={"content": "Zu löschen"})
        note_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/notes/{note_id}")
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT

        # Sicherstellen, dass die Notiz nicht mehr existiert
        get_resp = await client.get("/notes")
        ids = [n["id"] for n in get_resp.json()]
        assert note_id not in ids
