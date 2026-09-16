
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.models import Monitor
from app.schemas import MonitorCreate, MonitorResponse, StatsResponse

router = APIRouter(prefix="/api", tags=["monitors"])

@router.get("/monitors", response_model=list[MonitorResponse])
async def get_monitors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Monitor))
    return result.scalars().all()

@router.post("/monitors", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
async def create_monitor(monitor: MonitorCreate, db: AsyncSession = Depends(get_db)):
    from app.core.security import validate_ssrf_safe_url
    try:
        safe_url = validate_ssrf_safe_url(str(monitor.url))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    db_monitor = Monitor(
        name=monitor.name,
        url=safe_url,
        interval_seconds=monitor.interval_seconds,
        expected_status=monitor.expected_status,
        timeout=monitor.timeout
    )
    db.add(db_monitor)
    await db.commit()
    await db.refresh(db_monitor)
    return db_monitor

@router.get("/monitors/{monitor_id}", response_model=MonitorResponse)
async def get_monitor(monitor_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    monitor = result.scalar_one_or_none()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor

@router.delete("/monitors/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(monitor_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    monitor = result.scalar_one_or_none()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    await db.delete(monitor)
    await db.commit()

@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Monitor))
    monitors = result.scalars().all()
    
    total = len(monitors)
    up = sum(1 for m in monitors if m.is_up is True)
    down = sum(1 for m in monitors if m.is_up is False)
    
    latencies = [m.last_latency_ms for m in monitors if m.last_latency_ms is not None]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    
    return StatsResponse(
        total=total,
        up=up,
        down=down,
        avg_latency_ms=avg_latency
    )
