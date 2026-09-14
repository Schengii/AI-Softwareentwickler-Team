import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


def mask_pii(data: Any) -> Any:
    """Maskiert PII-Daten wie E-Mails in JSON-Strukturen."""
    if isinstance(data, dict):
        return {k: mask_pii(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_pii(v) for v in data]
    elif isinstance(data, str):
        # Ersetze E-Mails durch Maske
        return re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '***@***.com', data)
    return data

def pseudonymize_user_id(user_id: str) -> str:
    """Pseudonymisiert E-Mail-Adressen als user_id."""
    if "@" in user_id:
        return hashlib.sha256(user_id.encode()).hexdigest()[:32]
    return user_id

class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self):
        super().__init__(AuditLog)

    async def create_masked(self, db: AsyncSession, obj_in: dict[str, Any]) -> AuditLog:
        """Erstellt einen AuditLog-Eintrag mit DSGVO-konformer Maskierung."""
        if "changes" in obj_in:
            obj_in["changes"] = mask_pii(obj_in["changes"])
        if "user_id" in obj_in and isinstance(obj_in["user_id"], str):
            obj_in["user_id"] = pseudonymize_user_id(obj_in["user_id"])
            
        db_obj = AuditLog(**obj_in)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def get_for_tenant(self, db: AsyncSession, tenant_id: str, skip: int = 0, limit: int = 100) -> list[AuditLog]:
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def cleanup_old_logs(self, db: AsyncSession, days: int = 90) -> int:
        """Data Retention Policy: Löscht AuditLogs, die älter als X Tage sind."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        if hasattr(AuditLog, "created_at"):
            result = await db.execute(
                delete(AuditLog).where(AuditLog.created_at < cutoff)
            )
            await db.commit()
            return result.rowcount
        return 0

audit_log_repo = AuditLogRepository()
