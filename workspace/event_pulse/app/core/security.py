import os

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.dispatcher import verify_signature

# In einer echten Anwendung sollte dies aus Pydantic BaseSettings kommen
INCOMING_WEBHOOK_SECRET = os.getenv("INCOMING_WEBHOOK_SECRET", "dev_secret_key_123")

signature_header = APIKeyHeader(name="X-Signature", auto_error=False)

async def verify_incoming_webhook(
    request: Request,
    signature: str = Security(signature_header)
) -> None:
    """
    FastAPI Dependency zur Validierung der HMAC-SHA256 Signatur eingehender Events.
    Beinhaltet Replay-Schutz durch Timestamp-Validierung.
    """
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Missing X-Signature header"
        )
    
    # Body auslesen (FastAPI cacht den Body, sodass er später im Pydantic-Model noch verfügbar ist)
    body = await request.body()
    
    is_valid = verify_signature(
        secret=INCOMING_WEBHOOK_SECRET,
        header_value=signature,
        payload_bytes=body,
        tolerance_seconds=300
    )
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid signature or replay attack detected"
        )
