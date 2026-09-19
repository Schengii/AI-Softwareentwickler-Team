import hashlib
import hmac
import time

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import get_settings
from app.db.base import async_session_maker
from app.db.models import IdempotencyKey

settings = get_settings()

async def get_db():
    async with async_session_maker() as session:
        yield session

async def verify_signature(
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_timestamp: str = Header(None)
):
    if not x_hub_signature_256:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing signature header")
    
    if not x_timestamp:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing timestamp header")
        
    try:
        timestamp = int(x_timestamp)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timestamp format")
        
    current_time = time.time()
    # 5 minutes tolerance for replay protection
    if abs(current_time - timestamp) > 300:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Timestamp out of tolerance (Replay protection)")

    body = await request.body()
    
    # Use HMAC_SECRET_KEY if available, otherwise fallback to SECRET_KEY
    secret = getattr(settings, 'HMAC_SECRET_KEY', settings.SECRET_KEY).encode('utf-8')
    
    # Payload for signature includes timestamp to prevent replay
    payload_to_sign = f"{x_timestamp}:".encode() + body
    
    expected_signature = hmac.new(
        secret,
        msg=payload_to_sign,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    actual_signature = x_hub_signature_256
    actual_signature = actual_signature.removeprefix("sha256=")
        
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
        
    return True

async def check_idempotency(
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db)
):
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key header is required")
        
    stmt = select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key)
    result = await db.execute(stmt)
    existing_key = result.scalar_one_or_none()
    
    if existing_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key already exists")
        
    return idempotency_key
