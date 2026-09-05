import hashlib
import hmac

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.security import verify_webhook_signature

app = FastAPI()

@app.post("/webhook", dependencies=[Depends(verify_webhook_signature)])
async def webhook_endpoint():
    return {"status": "ok"}

client = TestClient(app)

def test_valid_signature():
    secret = settings.WEBHOOK_SECRET.encode("utf-8")
    body = b'{"event": "test"}'
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    
    response = client.post("/webhook", content=body, headers={"X-Webhook-Signature": signature})
    assert response.status_code == 200

def test_invalid_signature():
    body = b'{"event": "test"}'
    response = client.post("/webhook", content=body, headers={"X-Webhook-Signature": "invalid"})
    assert response.status_code == 403

def test_missing_header():
    response = client.post("/webhook", content=b'{"event": "test"}')
    assert response.status_code == 422

def test_empty_body():
    secret = settings.WEBHOOK_SECRET.encode("utf-8")
    body = b''
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    response = client.post("/webhook", content=body, headers={"X-Webhook-Signature": signature})
    assert response.status_code == 200
