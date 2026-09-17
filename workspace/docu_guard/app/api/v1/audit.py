from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.session import get_db
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogOut, AuditVerifyResult
from app.services.audit_chain import AuditChainService

router = APIRouter()

@router.get("/logs", response_model=list[AuditLogOut])
async def get_audit_logs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AuditLog).order_by(AuditLog.id.desc()))
    return result.scalars().all()

@router.get("/verify", response_model=AuditVerifyResult)
async def verify_audit_chain(db: AsyncSession = Depends(get_db)):
    is_valid, message = await AuditChainService.verify_chain(db)
    return AuditVerifyResult(is_valid=is_valid, message=message)
