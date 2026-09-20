import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_workflow_lifecycle():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create definition
        def_payload = {
            "name": "Invoice Approval",
            "initial_state": "DRAFT",
            "states": ["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED"],
            "transitions": [
                {"from": "DRAFT", "to": "IN_REVIEW", "action": "SUBMIT"},
                {"from": "IN_REVIEW", "to": "APPROVED", "action": "APPROVE", "guards": ["role == admin"]},
                {"from": "IN_REVIEW", "to": "REJECTED", "action": "REJECT"}
            ]
        }
        resp = await ac.post("/api/workflows/definitions", json=def_payload)
        assert resp.status_code == 201
        def_id = resp.json()["id"]

        # Create instance
        inst_payload = {
            "definition_id": def_id,
            "actor_id": "user1",
            "data": {"amount": 100}
        }
        resp = await ac.post("/api/workflows/instances", json=inst_payload)
        assert resp.status_code == 201
        inst_id = resp.json()["id"]
        assert resp.json()["current_state"] == "DRAFT"

        # Transition to IN_REVIEW
        trans_payload = {
            "action": "SUBMIT",
            "actor_id": "user1"
        }
        resp = await ac.post(f"/api/workflows/instances/{inst_id}/transitions", json=trans_payload)
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "IN_REVIEW"

        # Transition to APPROVED (fails guard)
        trans_payload = {
            "action": "APPROVE",
            "actor_id": "user2",
            "payload": {"role": "user"}
        }
        resp = await ac.post(f"/api/workflows/instances/{inst_id}/transitions", json=trans_payload)
        assert resp.status_code == 400

        # Transition to APPROVED (passes guard)
        trans_payload = {
            "action": "APPROVE",
            "actor_id": "admin1",
            "payload": {"role": "admin"}
        }
        resp = await ac.post(f"/api/workflows/instances/{inst_id}/transitions", json=trans_payload)
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "APPROVED"

        # Check Audit Log
        resp = await ac.get(f"/api/workflows/instances/{inst_id}/audit")
        assert resp.status_code == 200
        audit_log = resp.json()
        assert len(audit_log) == 3
        assert audit_log[0]["action"] == "CREATE"
        assert audit_log[1]["action"] == "SUBMIT"
        assert audit_log[2]["action"] == "APPROVE"
        
        # Verify hash chain
        assert audit_log[0]["prev_hash"] == "0" * 64
        assert audit_log[1]["prev_hash"] == audit_log[0]["current_hash"]
        assert audit_log[2]["prev_hash"] == audit_log[1]["current_hash"]
