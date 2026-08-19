import hmac, hashlib, os
from fastapi import Request, HTTPException, Header

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET").encode()

async def verify_signature(payload: bytes, signature: str = Header(...)):
    """Verifiziert Stripe/Calendly Webhook Signaturen."""
    expected = hmac.new(WEBHOOK_SECRET, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

# Beispiel: Webhook für Calendly-Interview-Bestätigung
async def handle_interview_webhook(request: Request):
    payload = await request.body()
    await verify_signature(payload, request.headers.get("X-Signature"))
    # Dispatch an Event-Queue (z.B. RabbitMQ/SQS) für asynchrone Verarbeitung
    return {"status": "accepted"}
