import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# In Produktion aus Umgebungsvariable laden
WEBHOOK_SECRET = b"super-secret-key"

async def verify_signature(
    request: Request,
    x_opspilot_signature: str = Header(..., alias="X-OpsPilot-Signature")
):
    payload = await request.body()
    expected_signature = hmac.new(
        WEBHOOK_SECRET,
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, x_opspilot_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    return True

@router.post("/ingest", status_code=202, dependencies=[Depends(verify_signature)])
async def ingest_webhook(payload: dict):
    """
    Nimmt externe Webhooks entgegen und validiert die Signatur.
    """
    # Hier erfolgt die asynchrone Weiterverarbeitung (z.B. Task-Queue)
    return {"status": "accepted"}
