import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all import AuditLog


def mask_pii(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    masked = data.copy()
    pii_keys = {"password", "secret", "api_key", "token", "email", "key"}
    for k, v in masked.items():
        if k.lower() in pii_keys:
            masked[k] = "***MASKED***"
        elif isinstance(v, dict):
            masked[k] = mask_pii(v)
    return masked

async def log_audit(db: AsyncSession, api_key_id: int, action: str, resource: str, details: dict = None):
    if details:
        details = mask_pii(details)
    log_entry = AuditLog(
        api_key_id=api_key_id,
        action=action,
        resource=resource,
        details=json.dumps(details) if details else None
    )
    db.add(log_entry)
    await db.commit()
