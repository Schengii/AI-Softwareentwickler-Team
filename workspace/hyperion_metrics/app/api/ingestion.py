import asyncio
import time
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.database import save_metric_db, save_metrics_batch_db
from app.models.schemas import MetricBatch, MetricItem, WindowAggregate
from app.services.aggregator import aggregator_service
from app.services.alerting import alert_engine
from app.services.pubsub import pubsub_manager

router = APIRouter(tags=["Metrics Ingestion & Aggregation"])


@router.post("/metrics", status_code=status.HTTP_202_ACCEPTED)
@router.post("/api/v1/metrics", status_code=status.HTTP_202_ACCEPTED)
async def ingest_metric(metric: MetricItem):
    """Nimmt einen einzelnen Metrik-Datenpunkt entgegen, speichert ihn persistent und aggregiert ihn."""
    # Persistente I/O-Speicherung (SQLite)
    await save_metric_db(metric)

    # In-Memory Sliding-Window Puffer
    aggregator_service.add_metric(metric)

    # Broadcast über WebSocket
    await pubsub_manager.broadcast({
        "type": "metric",
        "data": metric.model_dump(),
    })

    # Alert-Regeln prüfen
    await alert_engine.evaluate_metric(metric.name)

    return {"status": "accepted", "metric": metric.name}


@router.post("/metrics/batch", status_code=status.HTTP_202_ACCEPTED)
@router.post("/api/v1/metrics/batch", status_code=status.HTTP_202_ACCEPTED)
async def ingest_metric_batch(batch: MetricBatch):
    """Nimmt einen Batch von Metriken entgegen, persistiert und verarbeitet sie."""
    # Persistente I/O-Speicherung (SQLite Batch)
    await save_metrics_batch_db(batch.metrics)

    affected_metrics = set()
    for metric in batch.metrics:
        aggregator_service.add_metric(metric)
        affected_metrics.add(metric.name)
        await pubsub_manager.broadcast({
            "type": "metric",
            "data": metric.model_dump(),
        })

    for name in affected_metrics:
        await alert_engine.evaluate_metric(name)

    return {"status": "accepted", "count": len(batch.metrics)}


@router.get("/metrics/stats", response_model=WindowAggregate)
@router.get("/metrics/aggregate", response_model=WindowAggregate)
@router.get("/api/v1/metrics/aggregate", response_model=WindowAggregate)
@router.get("/api/v1/metrics/stats", response_model=WindowAggregate)
async def get_metrics_stats(
    metric_name: Optional[str] = Query(None, description="Name der Metrik"),
    name: Optional[str] = Query(None, description="Alternativer Name-Parameter"),
    window_seconds: float = Query(60.0, description="Dauer des gleitenden Fensters in Sekunden", gt=0),
):
    """Liefert aggregierte Statistiken (p50, p95, p99, Durchsatz, Fehlerrate) für ein Zeitfenster."""
    target_name = metric_name or name
    if not target_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter 'metric_name' oder 'name' ist erforderlich."
        )

    aggregate = aggregator_service.get_aggregate(target_name, window_seconds)
    return aggregate
