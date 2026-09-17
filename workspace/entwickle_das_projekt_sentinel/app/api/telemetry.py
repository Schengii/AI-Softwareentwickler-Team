
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.buffer import telemetry_buffer
from app.db.models import Telemetry
from app.db.session import get_db
from app.schemas.telemetry import TelemetryIngest, TelemetryResponse, TelemetryStats

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])

@router.post("/ingest", status_code=201)
async def ingest_telemetry(payload: TelemetryIngest):
    item = payload.model_dump()
    success = telemetry_buffer.add(item)
    if not success:
        raise HTTPException(status_code=429, detail="Buffer full, backpressure applied")
    return {"status": "accepted"}

@router.get("/stats", response_model=TelemetryStats)
async def get_stats(db: AsyncSession = Depends(get_db)):
    result_total = await db.execute(select(func.count()).select_from(Telemetry))
    total = result_total.scalar() or 0
    
    result_anomaly = await db.execute(select(func.count()).select_from(Telemetry).where(Telemetry.is_anomaly == True))
    anomalies = result_anomaly.scalar() or 0
    
    return TelemetryStats(total_count=total, anomaly_count=anomalies)

@router.get("/history", response_model=list[TelemetryResponse])
async def get_history(device_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Telemetry).where(Telemetry.device_id == device_id).order_by(Telemetry.timestamp.desc()).limit(100))
    return result.scalars().all()
