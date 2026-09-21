from fastapi import APIRouter, HTTPException

from app.models import MetricStats
from app.engine import engine

router = APIRouter()

@router.get("/stats/{name}", response_model=MetricStats)
async def read_metric_stats(name: str):
    """
    Gibt die Statistiken für eine bestimmte Metrik zurück.
    """
    stats = engine.get_stats(name)
    if not stats:
        raise HTTPException(status_code=404, detail="Metric not found")
    return stats
