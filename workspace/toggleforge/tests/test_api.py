"""Integrations- und Smoke-Tests für alle REST-Endpunkte."""

import pytest
from httpx import AsyncClient

from app.schemas import EvaluateResponse, FeatureFlagOut


@pytest.mark.asyncio
async def test_smoke_health_and_root(client: AsyncClient):
    """Smoke-Test: Prüft Health-Check und Auslieferung der Startseite."""
    health_res = await client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json() == {"status": "ok"}

    index_res = await client.get("/")
    assert index_res.status_code == 200


@pytest.mark.asyncio
async def test_flag_crud_roundtrip(client: AsyncClient):
    """Prüft vollständigen CRUD-Zyklus für ein Feature-Flag."""
    # 1. Flag anlegen (POST)
    payload = {
        "key": "search_v2",
        "name": "Neue Suche",
        "description": "Elastische Suche aktivieren",
        "flag_type": "boolean",
        "enabled": False,
        "rollout_percentage": 0,
        "targeting_rules": [],
    }
    create_res = await client.post("/api/v1/flags", json=payload)
    assert create_res.status_code == 201
    created_flag = FeatureFlagOut.model_validate(create_res.json())
    assert created_flag.key == "search_v2"

    # 2. Lesen (GET /flags/{key})
    get_res = await client.get("/api/v1/flags/search_v2")
    assert get_res.status_code == 200
    fetched_flag = FeatureFlagOut.model_validate(get_res.json())
    assert fetched_flag.enabled is False

    # 3. Aktualisieren (PUT /flags/{key})
    update_res = await client.put("/api/v1/flags/search_v2", json={"enabled": True})
    assert update_res.status_code == 200
    assert update_res.json()["enabled"] is True

    # 4. Liste abrufen (GET /flags)
    list_res = await client.get("/api/v1/flags")
    assert list_res.status_code == 200
    keys = [item["key"] for item in list_res.json()]
    assert "search_v2" in keys

    # 5. Löschen (DELETE /flags/{key})
    delete_res = await client.delete("/api/v1/flags/search_v2")
    assert delete_res.status_code == 204

    # 6. Verifizieren, dass Flag gelöscht ist
    not_found_res = await client.get("/api/v1/flags/search_v2")
    assert not_found_res.status_code == 404


@pytest.mark.asyncio
async def test_evaluate_endpoint_percentage(client: AsyncClient):
    """Prüft den Auswertungsendpunkt für Percentage-Rollouts."""
    flag_payload = {
        "key": "canary_service",
        "name": "Canary Service",
        "flag_type": "percentage",
        "enabled": True,
        "rollout_percentage": 100,
        "targeting_rules": [],
    }
    await client.post("/api/v1/flags", json=flag_payload)

    eval_payload = {
        "flag_key": "canary_service",
        "entity_id": "client_abc",
        "attributes": {},
    }
    eval_res = await client.post("/api/v1/evaluate", json=eval_payload)
    assert eval_res.status_code == 200
    validated = EvaluateResponse.model_validate(eval_res.json())
    assert validated.enabled is True
    assert validated.reason == "percentage_rollout_match"


@pytest.mark.asyncio
async def test_audit_logs_recorded(client: AsyncClient):
    """Verifiziert, dass Flag-Modifikationen im Audit-Log festgehalten werden."""
    flag_payload = {
        "key": "audit_test",
        "name": "Audit Test Flag",
        "flag_type": "boolean",
        "enabled": True,
        "rollout_percentage": 0,
        "targeting_rules": [],
    }
    await client.post("/api/v1/flags", json=flag_payload)

    audit_res = await client.get("/api/v1/audit?flag_key=audit_test")
    assert audit_res.status_code == 200
    logs = audit_res.json()
    assert len(logs) >= 1
    assert logs[0]["action"] == "create"
    assert logs[0]["flag_key"] == "audit_test"
