
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])

@router.post("", response_model=schemas.LogEntryResponse)
async def create_log(log: schemas.LogEntryCreate, db: AsyncSession = Depends(get_db)):
    db_log = models.LogEntry(**log.model_dump())
    db.add(db_log)
    await db.commit()
    await db.refresh(db_log)
    return db_log

@router.get("", response_model=list[schemas.LogEntryResponse])
async def read_logs(
    level: str | None = None,
    source: str | None = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(models.LogEntry)
    if level:
        query = query.filter(models.LogEntry.level == level)
    if source:
        query = query.filter(models.LogEntry.source == source)
    
    query = query.order_by(models.LogEntry.timestamp.desc())
    result = await db.execute(query)
    return result.scalars().all()
