"""API-Router für Metriken und Machine Learning (Health-Score)."""

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from app.ml.predictor import predictor

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics & ML"])

class HealthScoreResponse(BaseModel):
    """Pydantic V2 Schema für die Health-Score-Antwort."""
    model_config = ConfigDict(from_attributes=True)
    
    service_name: str
    health_score: float
    failure_probability: float
    status: str


@router.get("/health-score", response_model=HealthScoreResponse)
async def get_health_score(
    service_name: str = Query("default", description="Name des zu prüfenden Services"),
    total_requests: int = Query(100, ge=0, description="Gesamtzahl der Anfragen"),
    failed_requests: int = Query(0, ge=0, description="Anzahl der fehlgeschlagenen Anfragen"),
    recent_failures: int = Query(0, ge=0, description="Anzahl kürzlicher Fehler"),
    avg_latency_ms: float = Query(150.0, ge=0.0, description="Durchschnittliche Latenz in ms"),
    trend: float = Query(0.0, ge=-1.0, le=1.0, description="Fehlertrend (-1.0 bis 1.0)")
) -> HealthScoreResponse:
    """
    Berechnet den statistischen Health-Score und die Ausfallwahrscheinlichkeit eines Services.
    Nutzt das ML/Predictor-Modul zur Auswertung der übergebenen Telemetriedaten.
    """
    # Health-Score berechnen
    score = predictor.calculate_health_score(
        total_requests=total_requests,
        failed_requests=failed_requests,
        recent_failures=recent_failures,
        avg_latency_ms=avg_latency_ms
    )
    
    # Ausfallwahrscheinlichkeit berechnen
    failure_rate = failed_requests / total_requests if total_requests > 0 else 0.0
    prob = predictor.predict_failure_probability(
        recent_failure_rate=failure_rate, 
        trend=trend
    )
    
    # Status ableiten
    status = "HEALTHY"
    if score < 50.0:
        status = "CRITICAL"
    elif score < 80.0:
        status = "WARNING"
        
    return HealthScoreResponse(
        service_name=service_name,
        health_score=round(score, 2),
        failure_probability=round(prob, 4),
        status=status
    )
