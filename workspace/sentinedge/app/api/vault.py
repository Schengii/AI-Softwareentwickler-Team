import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.crypto import crypto_service
from app.core.database import get_db
from app.core.security import RequireScope
from app.models.all import ApiKey, Secret
from app.schemas.all import SecretCreate, SecretResponse, SecretValueResponse
from app.services.audit import log_audit

router = APIRouter(prefix="/api/secrets", tags=["secrets"])

@router.post("", response_model=SecretResponse)
async def create_secret(
    secret_in: SecretCreate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(RequireScope("secrets:write"))
):
    # Check for existing versions to increment version number
    result = await db.execute(
        select(Secret).where(Secret.key == secret_in.key).order_by(desc(Secret.version)).limit(1)
    )
    latest_secret = result.scalar_one_or_none()
    new_version = (latest_secret.version + 1) if latest_secret else 1

    encrypted_val = crypto_service.encrypt(secret_in.value)
    
    ttl_expires_at = None
    if secret_in.ttl_seconds:
        ttl_expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=secret_in.ttl_seconds)

    new_secret = Secret(
        key=secret_in.key,
        encrypted_value=encrypted_val,
        version=new_version,
        ttl_expires_at=ttl_expires_at
    )
    db.add(new_secret)
    await db.commit()
    await db.refresh(new_secret)

    await log_audit(db, api_key.id, "create_secret", secret_in.key, {"version": new_version})
    return new_secret

@router.get("/{key}", response_model=SecretValueResponse)
async def get_secret(
    key: str,
    version: int = None,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(RequireScope("secrets:read"))
):
    query = select(Secret).where(Secret.key == key)
    if version:
        query = query.where(Secret.version == version)
    else:
        query = query.order_by(desc(Secret.version)).limit(1)
        
    result = await db.execute(query)
    secret = result.scalar_one_or_none()

    if not secret:
        raise HTTPException(status_code=404, detail="Secret not found")

    if secret.ttl_expires_at and secret.ttl_expires_at.replace(tzinfo=datetime.timezone.utc) < datetime.datetime.now(datetime.timezone.utc):
        raise HTTPException(status_code=410, detail="Secret has expired")

    decrypted_val = crypto_service.decrypt(secret.encrypted_value)
    
    await log_audit(db, api_key.id, "read_secret", key, {"version": secret.version})
    
    return SecretValueResponse(
        key=secret.key,
        value=decrypted_val,
        version=secret.version
    )
