import hashlib
import hmac
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Endpoint
from app.main import app


@pytest.mark.asyncio
async def test_webhook_ingestion_hmac_validation(override_get_db, db_session):
    # Setup: Endpoint in DB anlegen
    secret = "super-secret-key"
    endpoint = Endpoint(url="http://example.com", secret=secret, is_active=True)
    db_session.add(endpoint)
    await db_session.commit()
    await db_session.refresh(endpoint)
    
    # Payload und Signatur vorbereiten
    payload = {"event": "test_event"}
    payload_json = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        secret.encode("utf-8"),
        payload_json,
        hashlib.sha256
    ).hexdigest()
    
    # Request senden
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/webhooks/ingest/{endpoint.id}",
            content=payload_json,
            headers={
                "X-Signature": signature,
                "X-Idempotency-Key": str(uuid.uuid4()),
                "Content-Type": "application/json"
            }
        )
    
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
