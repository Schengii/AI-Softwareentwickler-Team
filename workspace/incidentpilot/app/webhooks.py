import hashlib
import hmac
import json
import logging
import os

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from tenacity import retry, stop_after_attempt, wait_exponential

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger("app.webhooks")

# Secret MUSS gesetzt sein, Default für Tests setzen
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "test-secret-key-for-dev-and-tests")
WEBHOOK_SECRET_BYTES = WEBHOOK_SECRET.encode()

async def verify_signature(payload: bytes, signature: str):
    """Verifiziert HMAC-SHA256 Signatur."""
    expected_signature = hmac.new(WEBHOOK_SECRET_BYTES, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_signature, signature)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
async def dispatch_webhook(url: str, data: dict):
    """Sendet Webhook mit Retry-Logik."""
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=data, timeout=10.0)
        response.raise_for_status()
        logger.info(f"Webhook delivered to {url} with status {response.status_code}")

from app.models import save_incident
from app.schemas import WebhookPayload


@router.post("/receive")
async def receive_webhook(
    request: Request, 
    background_tasks: BackgroundTasks,
    x_signature: str = Header(None)
):
    """Empfängt Webhooks von externen Systemen."""
    if not x_signature:
        raise HTTPException(status_code=401, detail="Missing signature")
    
    body = await request.body()
    if not await verify_signature(body, x_signature):
        logger.warning("Invalid webhook signature attempt")
        raise HTTPException(status_code=403, detail="Invalid signature")
    
    try:
        payload_dict = await request.json()
        payload = WebhookPayload(**payload_dict)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    background_tasks.add_task(save_incident, payload.event_type, payload_dict)
    
    return {"status": "accepted"}
