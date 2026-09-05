import hashlib
import hmac
import logging

from fastapi import Header, HTTPException, Request, status

from app.core.config import settings

# Logger für Security-Audits konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("security")

async def verify_webhook_signature(
    request: Request,
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature")
):
    """
    Verifiziert die HMAC-SHA256 Signatur des Webhook-Requests.
    Implementiert Schutz gegen Timing-Attacken und Logging für Audits.
    """
    if not settings.WEBHOOK_SECRET or settings.WEBHOOK_SECRET == "super-secret-dev-key-change-me":
        logger.critical("WEBHOOK_SECRET is missing or insecurely configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Security configuration error"
        )

    try:
        body = await request.body()
    except Exception as e:
        logger.error(f"Failed to read request body: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read request body"
        )
    
    # HMAC-SHA256 Berechnung
    expected_signature = hmac.new(
        settings.WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, x_webhook_signature):
        logger.warning("Security Alert: Invalid webhook signature attempt detected.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature"
        )
    
    return True
