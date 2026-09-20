import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_four_eyes_principle():
    """Testet, dass dieselbe Person nicht approve darf, die submitted hat."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Definition erstellen
        def_payload = {
            "name": "Four Eyes Test",
            "initial_state": "DRAFT",
            "states": ["DRAFT", "IN_REVIEW", "APPROVED"],
            "transitions": [
                {"from": "DRAFT", "to": "IN_REVIEW", "action": "SUBMIT"},
                {"from": "IN_REVIEW", "to": "APPROVED", "action": "APPROVE", "guards": ["actor != submitter"]}
            ]
        }
        resp = await ac.post("/api/workflows/definitions", json=def_payload)
        def_id = resp.json()["id"]

        # Instanz erstellen
        resp = await ac.post("/api/workflows/instances", json={"definition_id": def_id, "actor_id": "user1"})
        inst_id = resp.json()["id"]

        # Submit
        await ac.post(f"/api/workflows/instances/{inst_id}/transitions", json={"action": "SUBMIT", "actor_id": "user1"})

        # Approve durch denselben User (sollte fehlschlagen)
        resp = await ac.post(f"/api/workflows/instances/{inst_id}/transitions", json={"action": "APPROVE", "actor_id": "user1"})
        assert resp.status_code == 400
        
        # Approve durch anderen User (sollte erfolgreich sein)
        resp = await ac.post(f"/api/workflows/instances/{inst_id}/transitions", json={"action": "APPROVE", "actor_id": "user2"})
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "APPROVED"
