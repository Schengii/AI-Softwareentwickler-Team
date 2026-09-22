from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import decrypt_value, encrypt_value
from app.models.audit import AuditLog
from app.models.vault_item import Secret, SecretStatus


class SecretCreate(BaseModel):
    name: str
    value: str
    ttl_seconds: int | None = None
    metadata: dict | None = None

async def log_audit(db: AsyncSession, action: str, secret_name: str, actor_ip: str, status_msg: str):
    log = AuditLog(
        action=action,
        secret_name=secret_name,
        actor_ip=actor_ip,
        status=status_msg
    )
    db.add(log)
    await db.commit()

async def create_secret(db: AsyncSession, secret_in: SecretCreate, actor_ip: str) -> Secret:
    result = await db.execute(select(Secret).where(Secret.name == secret_in.name))
    existing = result.scalars().first()
    if existing:
        await log_audit(db, "create", secret_in.name, actor_ip, "failed: already exists")
        raise HTTPException(status_code=400, detail="Secret already exists")

    encrypted_val = encrypt_value(secret_in.value)
    expires_at = None
    if secret_in.ttl_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=secret_in.ttl_seconds)

    secret = Secret(
        name=secret_in.name,
        encrypted_value=encrypted_val,
        ttl_seconds=secret_in.ttl_seconds,
        metadata_json=secret_in.metadata,
        expires_at=expires_at
    )
    db.add(secret)
    await db.commit()
    await db.refresh(secret)
    await log_audit(db, "create", secret.name, actor_ip, "success")
    return secret

async def get_secret(db: AsyncSession, name: str, actor_ip: str) -> str:
    result = await db.execute(select(Secret).where(Secret.name == name))
    secret = result.scalars().first()
    if not secret:
        await log_audit(db, "read", name, actor_ip, "failed: not found")
        raise HTTPException(status_code=404, detail="Secret not found")
    
    if secret.status != SecretStatus.active:
        await log_audit(db, "read", name, actor_ip, f"failed: {secret.status.value}")
        raise HTTPException(status_code=400, detail=f"Secret is {secret.status.value}")

    if secret.expires_at and secret.expires_at < datetime.now(timezone.utc):
        secret.status = SecretStatus.expired
        await db.commit()
        await log_audit(db, "read", name, actor_ip, "failed: expired")
        raise HTTPException(status_code=400, detail="Secret is expired")

    decrypted_val = decrypt_value(secret.encrypted_value)
    await log_audit(db, "read", name, actor_ip, "success")
    return decrypted_val

async def revoke_secret(db: AsyncSession, name: str, actor_ip: str):
    result = await db.execute(select(Secret).where(Secret.name == name))
    secret = result.scalars().first()
    if not secret:
        await log_audit(db, "revoke", name, actor_ip, "failed: not found")
        raise HTTPException(status_code=404, detail="Secret not found")
    
    secret.status = SecretStatus.revoked
    await db.commit()
    await log_audit(db, "revoke", name, actor_ip, "success")
    return secret
