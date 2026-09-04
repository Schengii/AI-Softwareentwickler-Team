
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_db
from ..models import TimeEntry, Project

router = APIRouter()

@router.get("/summary")
async def get_report_summary(db: AsyncSession = Depends(get_db)) -> dict[str, float]:
    """
    Berechnet den Gesamtumsatz und die Gesamtdauer basierend auf Zeiteinträgen.
    Umsatz = Summe(Dauer in Stunden * Stundensatz des Projekts).
    """
    # Query für Zeiteinträge mit zugehörigem Projekt
    stmt = (
        select(
            func.sum(
                (func.extract('epoch', TimeEntry.end_time - TimeEntry.start_time) / 3600.0)
            ).label("total_hours"),
            func.sum(
                (func.extract('epoch', TimeEntry.end_time - TimeEntry.start_time) / 3600.0) * Project.hourly_rate
            ).label("total_revenue")
        )
        .join(Project, TimeEntry.project_id == Project.id)
        .where(TimeEntry.end_time.isnot(None))
    )
    
    result = await db.execute(stmt)
    row = result.one()
    
    return {
        "total_revenue": float(row.total_revenue or 0.0),
        "total_duration_hours": float(row.total_hours or 0.0)
    }
