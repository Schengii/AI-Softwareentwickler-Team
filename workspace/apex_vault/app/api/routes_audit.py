
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.audit import AuditLog, AuditLogResponse

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("", response_model=list[AuditLogResponse])
async def get_audit_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    result = await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()))
    logs = result.scalars().all()
    return logs
