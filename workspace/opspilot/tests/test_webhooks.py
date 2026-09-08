from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.webhooks import router

app = FastAPI()
app.include_router(router, prefix="/api/v1")

client = TestClient(app)

def test_webhook_ingest_invalid_signature():
    response = client.post(
        "/api/v1/webhooks/ingest",
        json={"test": "data"},
        headers={"X-OpsPilot-Signature": "wrong-sig"}
    )
    assert response.status_code == 401

def test_webhook_ingest_success():
    import hashlib
    import hmac
    
    payload = b'{"test": "data"}'
    secret = b"super-secret-key"
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    
    response = client.post(
        "/api/v1/webhooks/ingest",
        content=payload,
        headers={"X-OpsPilot-Signature": sig, "Content-Type": "application/json"}
    )
    assert response.status_code == 202
