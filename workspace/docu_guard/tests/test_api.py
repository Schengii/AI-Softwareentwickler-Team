import json

import pytest


@pytest.mark.asyncio
async def test_upload_document_flow(async_client):
    """Roundtrip: Dokument hochladen und in der Liste verifizieren."""
    # 1. Dokument erstellen
    payload = {
        "filename": "geheimes_projekt.txt",
        "content": "Streng vertrauliche Daten"
    }
    response = await async_client.post("/api/v1/documents/upload", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == payload["filename"]
    assert "id" in data
    
    # 2. Liste prüfen
    list_resp = await async_client.get("/api/v1/documents")
    assert list_resp.status_code == 200
    docs = list_resp.json()
    assert len(docs) >= 1
    assert any(d["id"] == data["id"] for d in docs)

@pytest.mark.asyncio
async def test_verify_audit_chain(async_client):
    """Prüft, ob für ein neues Dokument ein Audit-Log-Eintrag erstellt wird."""
    # 1. Dokument erstellen
    payload = {
        "filename": "audit_test.txt",
        "content": "Inhalt für Audit"
    }
    await async_client.post("/api/v1/documents/upload", json=payload)
    
    # 2. Audit-Logs abrufen
    logs_resp = await async_client.get("/api/v1/audit/logs")
    assert logs_resp.status_code == 200
    logs = logs_resp.json()
    
    assert len(logs) >= 1
    # Der erste Log-Eintrag sollte die Erstellung dokumentieren
    assert logs[0]["action"] == "UPLOAD"
    assert "document_id" in json.loads(logs[0]["payload"])
