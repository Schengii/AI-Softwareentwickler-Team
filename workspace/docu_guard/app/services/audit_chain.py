import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.audit import AuditLog


class AuditChainService:
    GENESIS_HASH = "0" * 64

    @staticmethod
    async def get_last_hash(db: AsyncSession) -> str:
        result = await db.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
        )
        last_log = result.scalars().first()
        return last_log.hash if last_log else AuditChainService.GENESIS_HASH

    @staticmethod
    def calculate_hash(prev_hash: str, timestamp_iso: str, action: str, payload: str) -> str:
        data = f"{prev_hash}{timestamp_iso}{action}{payload}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    async def log_action(db: AsyncSession, action: str, payload: dict) -> AuditLog:
        prev_hash = await AuditChainService.get_last_hash(db)
        timestamp = datetime.now(UTC)
        timestamp_iso = timestamp.isoformat()
        payload_str = json.dumps(payload, sort_keys=True)
        
        new_hash = AuditChainService.calculate_hash(prev_hash, timestamp_iso, action, payload_str)
        
        log_entry = AuditLog(
            timestamp=timestamp,
            action=action,
            payload=payload_str,
            prev_hash=prev_hash,
            hash=new_hash
        )
        db.add(log_entry)
        await db.commit()
        await db.refresh(log_entry)
        return log_entry

    @staticmethod
    async def verify_chain(db: AsyncSession) -> tuple[bool, str]:
        result = await db.execute(select(AuditLog).order_by(AuditLog.id.asc()))
        logs = result.scalars().all()
        
        expected_prev_hash = AuditChainService.GENESIS_HASH
        
        for log in logs:
            if log.prev_hash != expected_prev_hash:
                return False, f"Chain broken at log ID {log.id}: Invalid prev_hash."
            
            calculated_hash = AuditChainService.calculate_hash(
                log.prev_hash, log.timestamp.isoformat(), log.action, log.payload
            )
            
            if log.hash != calculated_hash:
                return False, f"Chain broken at log ID {log.id}: Hash mismatch."
                
            expected_prev_hash = log.hash
            
        return True, "Audit chain is valid."
