"""ChronosPulse API Einstiegspunkt.

Hochverfuegbare Observability- & Event-Streaming-Plattform fuer verteilte Mikrosysteme.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ml.anomaly_detector import anomaly_detector


class Settings(BaseSettings):
    """Zentrale Anwendungskonfiguration mit Dev-Defaults."""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "ChronosPulse API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./chronospulse.db"
    SECRET_KEY: str = Field(default_factory=lambda: "dev-secret-token-key-chronospulse-992384")
    CORS_ORIGINS: List[str] = ["*"]
    SSE_HEARTBEAT_INTERVAL: float = 1.0


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Gecachte Settings-Dependency."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Pydantic v2 Datenmodelle (SSoT)
class MetricEvent(BaseModel):
    """Eingehende Metrik fuer Ingestion."""
    model_config = ConfigDict(extra="ignore")

    metric_name: str = Field(..., description="Name der Metrik, z. B. http_request_duration_ms")
    value: float = Field(..., description="Gemessener Wert")
    service: str = Field(default="default-service", description="Quellservice")
    timestamp: float = Field(default_factory=lambda: time.time(), description="Messzeitpunkt (Unix Epoch)")
    tags: Dict[str, str] = Field(default_factory=dict, description="Metadaten-Tags")


class MetricRecord(MetricEvent):
    """Gespeicherter Metrik-Datensatz mit ID."""
    id: str = Field(default_factory=lambda: str(uuid4()))


class AnomalyEvent(BaseModel):
    """Erkannte oder gemeldete Anomalie."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid4()))
    metric_name: str
    service: str
    expected_value: float
    actual_value: float
    z_score: float = 0.0
    severity: str = "warning"  # warning, critical, info
    description: Optional[str] = None
    timestamp: float = Field(default_factory=lambda: time.time())
    acknowledged: bool = False


class WebhookPayload(BaseModel):
    """Eingehendes Webhook-Ereignis."""
    model_config = ConfigDict(extra="ignore")

    event_type: str
    source: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    secret: Optional[str] = None
    timestamp: float = Field(default_factory=lambda: time.time())


class WebhookRecord(WebhookPayload):
    """Persistiertes Webhook-Log."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: str = "processed"


# In-Memory Event Streaming Hub & Storage
class EventHub:
    """Zentraler SSE- und Metric-Broadcaster fuer Realtime-Updates."""

    def __init__(self) -> None:
        self.metric_subscribers: List[asyncio.Queue[MetricRecord]] = []
        self.metrics_history: List[MetricRecord] = []
        self.anomalies_history: List[AnomalyEvent] = []
        self.webhooks_history: List[WebhookRecord] = []
        self._lock = asyncio.Lock()

    async def add_metric(self, metric: MetricEvent) -> MetricRecord:
        record = MetricRecord(**metric.model_dump())
        async with self._lock:
            self.metrics_history.append(record)
            if len(self.metrics_history) > 10000:
                self.metrics_history = self.metrics_history[-10000:]
            # Broadcast an alle aktiven SSE Listener
            dead_queues = []
            for q in self.metric_subscribers:
                try:
                    q.put_nowait(record)
                except asyncio.QueueFull:
                    dead_queues.append(q)
            for dead in dead_queues:
                if dead in self.metric_subscribers:
                    self.metric_subscribers.remove(dead)
        return record

    async def register_metric_listener(self) -> asyncio.Queue[MetricRecord]:
        q: asyncio.Queue[MetricRecord] = asyncio.Queue(maxsize=500)
        async with self._lock:
            self.metric_subscribers.append(q)
        return q

    async def unregister_metric_listener(self, q: asyncio.Queue[MetricRecord]) -> None:
        async with self._lock:
            if q in self.metric_subscribers:
                self.metric_subscribers.remove(q)

    async def add_anomaly(self, anomaly: AnomalyEvent) -> AnomalyEvent:
        async with self._lock:
            self.anomalies_history.append(anomaly)
            if len(self.anomalies_history) > 5000:
                self.anomalies_history = self.anomalies_history[-5000:]
        return anomaly

    async def add_webhook(self, webhook: WebhookPayload) -> WebhookRecord:
        record = WebhookRecord(**webhook.model_dump())
        async with self._lock:
            self.webhooks_history.append(record)
            if len(self.webhooks_history) > 5000:
                self.webhooks_history = self.webhooks_history[-5000:]
        return record


event_hub = EventHub()


# Lifespan Context Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Anwendungs-Lebenszyklus: Initialisierung und Bereinigung."""
    # Startup: Beispiel-Initialisierung
    yield
    # Shutdown: Ressourcen aufraeumen
    pass


# Hauptanwendung
app = FastAPI(
    title="ChronosPulse API",
    version="1.0.0",
    description="Observability- & Event-Streaming-Plattform fuer verteilte Systeme",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Router: Metriken (/api/v1/metrics) ---
metrics_router = APIRouter(prefix="/metrics", tags=["Metrics"])


@metrics_router.post("", response_model=MetricRecord, status_code=status.HTTP_201_CREATED)
async def ingest_metric(metric: MetricEvent) -> MetricRecord:
    """Nimmt eine neue Metrik entgegen und speichert/streamt sie."""
    record = await event_hub.add_metric(metric)

    # Statistische Anomalieerkennung (Z-Score & EMA)
    is_anomaly, z_score, expected_value = anomaly_detector.update_and_detect(
        service=metric.service,
        metric_name=metric.metric_name,
        value=metric.value
    )

    if is_anomaly:
        severity = "critical" if abs(z_score) > 5.0 else "warning"
        anomaly = AnomalyEvent(
            metric_name=metric.metric_name,
            service=metric.service,
            expected_value=expected_value,
            actual_value=metric.value,
            z_score=z_score,
            severity=severity,
            description=f"Anomalie in {metric.service} für {metric.metric_name}: Z-Score {z_score:.2f}",
            timestamp=metric.timestamp,
        )
        await event_hub.add_anomaly(anomaly)

    return record


@metrics_router.get("", response_model=List[MetricRecord])
async def list_metrics(
    service: Optional[str] = Query(None, description="Nach Service filtern"),
    metric_name: Optional[str] = Query(None, description="Nach Metriknamen filtern"),
    limit: int = Query(50, ge=1, le=1000, description="Maximale Anzahl"),
) -> List[MetricRecord]:
    """Liefert historische Metriken mit Filteroptionen zurueck."""
    metrics = event_hub.metrics_history
    if service:
        metrics = [m for m in metrics if m.service == service]
    if metric_name:
        metrics = [m for m in metrics if m.metric_name == metric_name]
    return metrics[-limit:]


@metrics_router.get("/stream")
async def stream_metrics(request: Request) -> StreamingResponse:
    """Server-Sent Events (SSE) Endpunkt fuer Live-Metrik-Updates."""
    queue = await event_hub.register_metric_listener()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Sende Initial-Ping
            yield "event: connected\ndata: {\"status\": \"ready\"}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Warte auf neue Metriken im Buffer mit Timeout fuer Keepalive
                    record = await asyncio.wait_for(queue.get(), timeout=2.0)
                    payload = json.dumps(record.model_dump())
                    yield f"event: metric\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive Ping
                    yield f"event: ping\ndata: {{\"time\": {time.time()}}}\n\n"
        finally:
            await event_hub.unregister_metric_listener(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Router: Anomalien (/api/v1/anomalies) ---
anomalies_router = APIRouter(prefix="/anomalies", tags=["Anomalies"])


@anomalies_router.post("", response_model=AnomalyEvent, status_code=status.HTTP_201_CREATED)
async def report_anomaly(anomaly: AnomalyEvent) -> AnomalyEvent:
    """Registriert eine manuell oder extern erkannte Anomalie."""
    return await event_hub.add_anomaly(anomaly)


@anomalies_router.get("", response_model=List[AnomalyEvent])
async def list_anomalies(
    severity: Optional[str] = Query(None, description="Filter nach Schweregrad"),
    acknowledged: Optional[bool] = Query(None, description="Filter nach Bestaetigt-Status"),
    limit: int = Query(50, ge=1, le=500),
) -> List[AnomalyEvent]:
    """Gibt erkannte Anomalien zurueck."""
    anomalies = event_hub.anomalies_history
    if severity:
        anomalies = [a for a in anomalies if a.severity == severity]
    if acknowledged is not None:
        anomalies = [a for a in anomalies if a.acknowledged == acknowledged]
    return anomalies[-limit:]


@anomalies_router.patch("/{anomaly_id}/acknowledge", response_model=AnomalyEvent)
async def acknowledge_anomaly(anomaly_id: str) -> AnomalyEvent:
    """Markiert eine Anomalie als bestaetigt."""
    for a in event_hub.anomalies_history:
        if a.id == anomaly_id:
            a.acknowledged = True
            return a
    raise HTTPException(status_code=404, detail="Anomalie nicht gefunden")


# --- Router: Webhooks (/api/v1/webhooks) ---
webhooks_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@webhooks_router.post("", response_model=WebhookRecord, status_code=status.HTTP_201_CREATED)
async def receive_webhook(payload: WebhookPayload) -> WebhookRecord:
    """Empfaengt externe Webhook-Benachrichtigungen (z.B. PagerDuty, Alertmanager)."""
    record = await event_hub.add_webhook(payload)
    return record


@webhooks_router.get("", response_model=List[WebhookRecord])
async def list_webhooks(limit: int = Query(50, ge=1, le=500)) -> List[WebhookRecord]:
    """Liefert empfangene Webhooks zurueck."""
    return event_hub.webhooks_history[-limit:]


# Registrierung der Router mit /api/v1 Praefix
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(metrics_router)
api_v1_router.include_router(anomalies_router)
api_v1_router.include_router(webhooks_router)

app.include_router(api_v1_router)


# Health Check Endpunkt
@app.get("/health", tags=["System"])
async def health_check() -> Dict[str, Any]:
    """System-Status pruefen."""
    return {
        "status": "healthy",
        "service": "ChronosPulse",
        "timestamp": time.time(),
        "active_sse_clients": len(event_hub.metric_subscribers),
        "total_metrics": len(event_hub.metrics_history),
    }


# Frontend statisches Mounting (falls frontend/dist existiert)
frontend_dir = Path("frontend/dist")
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
