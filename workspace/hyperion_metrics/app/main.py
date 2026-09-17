"""hyperion_metrics - Asynchrones Metrik-Ingestion- & Alerting-System."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Modelle
# -----------------------------------------------------------------------------
class MetricRecord(BaseModel):
    name: str = Field(..., min_length=1, description="Name der Metrik")
    value: float = Field(..., description="Numerischer Metrikwert")
    timestamp: float | None = Field(
        default=None, description="Unix-Timestamp in Sekunden (optional)"
    )
    tags: dict[str, str] = Field(default_factory=dict, description="Zusatzattribute")


class MetricPoint:
    __slots__ = ("name", "tags", "timestamp", "value")

    def __init__(
        self,
        name: str,
        value: float,
        timestamp: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self.timestamp = timestamp
        self.tags = tags or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "timestamp": self.timestamp,
            "tags": self.tags,
        }


class AggregationResult(BaseModel):
    metric_name: str
    window_seconds: int
    count: int
    min: float
    max: float
    avg: float
    sum: float
    calculated_at: float


class AlertRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1)
    metric_name: str = Field(..., min_length=1)
    condition: Literal["gt", "gte", "lt", "lte", "eq"] = Field(
        ..., description="Vergleichsoperator: gt (>), gte (>=), lt (<), lte (<=), eq (==)"
    )
    threshold: float = Field(..., description="Schwellenwert")
    window_seconds: int = Field(
        default=60, gt=0, description="Sliding-Window für Aggregation"
    )
    aggregation: Literal["avg", "max", "min", "sum", "count", "last"] = Field(
        default="avg", description="Aggregationsfunktion"
    )
    enabled: bool = Field(default=True)


class AlertEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str
    rule_name: str
    metric_name: str
    current_value: float
    threshold: float
    condition: str
    triggered_at: float
    message: str


# -----------------------------------------------------------------------------
# WebSocket Connection Manager
# -----------------------------------------------------------------------------
class ConnectionManager:
    """Verwaltet aktive WebSocket-Verbindungen und verteilt Events."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast_json(self, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self.active_connections)

        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001 - Verbindung getrennt oder Client nicht erreichbar
                await self.disconnect(connection)


# -----------------------------------------------------------------------------
# Sliding Window Aggregator & Metrics Store
# -----------------------------------------------------------------------------
class MetricsAggregator:
    """Speichert Datenpunkte in Deques und berechnet Sliding-Window-Aggregate."""

    def __init__(self, max_retention_seconds: int = 3600) -> None:
        self.max_retention_seconds = max_retention_seconds
        self.data: dict[str, deque[MetricPoint]] = defaultdict(deque)

    def add(self, point: MetricPoint) -> None:
        queue = self.data[point.name]
        queue.append(point)
        # Alte Datenpunkte außerhalb des maximalen Fensters bereinigen
        cutoff = point.timestamp - self.max_retention_seconds
        while queue and queue[0].timestamp < cutoff:
            queue.popleft()

    def get_points_in_window(self, metric_name: str, window_seconds: int) -> list[MetricPoint]:
        queue = self.data.get(metric_name)
        if not queue:
            return []
        now = time.time()
        cutoff = now - window_seconds
        return [p for p in queue if p.timestamp >= cutoff]

    def aggregate(
        self, metric_name: str, window_seconds: int
    ) -> AggregationResult | None:
        points = self.get_points_in_window(metric_name, window_seconds)
        if not points:
            return None

        values = [p.value for p in points]
        count = len(values)
        total = sum(values)
        return AggregationResult(
            metric_name=metric_name,
            window_seconds=window_seconds,
            count=count,
            min=min(values),
            max=max(values),
            avg=total / count,
            sum=total,
            calculated_at=time.time(),
        )


# -----------------------------------------------------------------------------
# Alert Engine
# -----------------------------------------------------------------------------
class AlertEngine:
    """Verwaltet und evaluiert Alert-Regeln inklusive persistenter Speicherung."""

    def __init__(self, storage_path: str | None = None) -> None:
        self.rules: dict[str, AlertRule] = {}
        self.triggered_alerts: deque[AlertEvent] = deque(maxlen=200)
        self.storage_path = storage_path or os.getenv("ALERTS_STORAGE_PATH", "data/alert_rules.json")
        self._load_from_storage()

    def _load_from_storage(self) -> None:
        """Lädt persistierte Alert-Regeln von der Festplatte/Storage."""
        import json

        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                    for item in raw_data:
                        rule = AlertRule.model_validate(item)
                        self.rules[rule.id] = rule
            except (OSError, ValueError):
                pass

    async def persist_rules(self) -> None:
        """Schreibt den aktuellen Zustand der Alert-Regeln persistent in das Dateisystem."""
        import json

        def _write_file() -> None:
            dirname = os.path.dirname(self.storage_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump([r.model_dump() for r in self.rules.values()], f, indent=2)

        try:
            await asyncio.to_thread(_write_file)
        except OSError:
            pass

    def add_rule(self, rule: AlertRule) -> AlertRule:
        self.rules[rule.id] = rule
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self.rules:
            del self.rules[rule_id]
            return True
        return False

    def get_rules(self) -> list[AlertRule]:
        return list(self.rules.values())

    def evaluate(
        self, aggregator: MetricsAggregator, new_point: MetricPoint
    ) -> list[AlertEvent]:
        new_alerts: list[AlertEvent] = []
        for rule in self.rules.values():
            if not rule.enabled or rule.metric_name != new_point.name:
                continue

            current_val: float | None = None
            if rule.aggregation == "last":
                current_val = new_point.value
            else:
                agg = aggregator.aggregate(rule.metric_name, rule.window_seconds)
                if agg:
                    if rule.aggregation == "avg":
                        current_val = agg.avg
                    elif rule.aggregation == "max":
                        current_val = agg.max
                    elif rule.aggregation == "min":
                        current_val = agg.min
                    elif rule.aggregation == "sum":
                        current_val = agg.sum
                    elif rule.aggregation == "count":
                        current_val = float(agg.count)

            if current_val is None:
                continue

            triggered = False
            op = rule.condition
            thresh = rule.threshold
            if op == "gt" and current_val > thresh or op == "gte" and current_val >= thresh or op == "lt" and current_val < thresh or op == "lte" and current_val <= thresh or op == "eq" and current_val == thresh:
                triggered = True

            if triggered:
                event = AlertEvent(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    metric_name=rule.metric_name,
                    current_value=round(current_val, 4),
                    threshold=thresh,
                    condition=op,
                    triggered_at=time.time(),
                    message=f"Alert '{rule.name}': {rule.metric_name} ({rule.aggregation}) is {round(current_val, 4)} {op} {thresh}",
                )
                self.triggered_alerts.append(event)
                new_alerts.append(event)

        return new_alerts


# -----------------------------------------------------------------------------
# Globale Instanzen & Hintergrund-Worker
# -----------------------------------------------------------------------------
ingestion_queue: asyncio.Queue[MetricPoint] = asyncio.Queue()
connection_manager = ConnectionManager()
metrics_aggregator = MetricsAggregator()
alert_engine = AlertEngine()
_worker_task: asyncio.Task[None] | None = None


async def process_metrics_worker() -> None:
    """Hintergrund-Worker zur Abarbeitung der Ingestion-Queue."""
    while True:
        try:
            point = await ingestion_queue.get()
            metrics_aggregator.add(point)

            # Alerts evaluieren
            alerts = alert_engine.evaluate(metrics_aggregator, point)

            # Live-Broadcast für Clients
            broadcast_payload = {
                "type": "metric",
                "data": point.to_dict(),
            }
            await connection_manager.broadcast_json(broadcast_payload)

            for alert in alerts:
                await connection_manager.broadcast_json(
                    {
                        "type": "alert",
                        "data": alert.model_dump(),
                    }
                )

            ingestion_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 - Worker darf bei Einzelfehlern nicht abbrechen
            await asyncio.sleep(0.01)


# -----------------------------------------------------------------------------
# FastAPI App & Lifespan
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task
    _worker_task = asyncio.create_task(process_metrics_worker())
    yield
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="hyperion_metrics",
    description="Asynchrones Metrik-Ingestion- und Alerting-System",
    version="1.0.0",
    lifespan=lifespan,
)


# -----------------------------------------------------------------------------
# API-Endpunkte
# -----------------------------------------------------------------------------
@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """Health-Check-Endpunkt."""
    return {"status": "ok"}


@app.post(
    "/api/v1/metrics",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Metrics"],
)
async def ingest_metric(metric: MetricRecord) -> dict[str, Any]:
    """Nimmt Metrik-Datenpunkte mit Sub-Millisekunden-Latenz entgegen."""
    ts = metric.timestamp if metric.timestamp is not None else time.time()
    point = MetricPoint(
        name=metric.name,
        value=metric.value,
        timestamp=ts,
        tags=metric.tags,
    )
    await ingestion_queue.put(point)
    return {"status": "accepted", "queued_at": ts}


@app.get("/api/v1/metrics/aggregate", tags=["Metrics"])
async def get_aggregation(
    name: str, window_seconds: int = 60
) -> dict[str, Any]:
    """Liefert berechnete Sliding-Window-Aggregationen für eine Metrik."""
    agg = metrics_aggregator.aggregate(name, window_seconds)
    if not agg:
        return {
            "metric_name": name,
            "window_seconds": window_seconds,
            "count": 0,
            "min": 0.0,
            "max": 0.0,
            "avg": 0.0,
            "sum": 0.0,
            "calculated_at": time.time(),
        }
    return agg.model_dump()


@app.get("/api/v1/alerts", response_model=list[AlertRule], tags=["Alerts"])
async def list_alert_rules() -> list[AlertRule]:
    """Liefert alle konfigurierten Alert-Regeln."""
    return alert_engine.get_rules()


@app.post(
    "/api/v1/alerts",
    response_model=AlertRule,
    status_code=status.HTTP_201_CREATED,
    tags=["Alerts"],
)
async def create_alert_rule(rule: AlertRule) -> AlertRule:
    """Erstellt eine neue Alert-Regel."""
    return alert_engine.add_rule(rule)


@app.delete("/api/v1/alerts/{rule_id}", tags=["Alerts"])
async def delete_alert_rule(rule_id: str) -> dict[str, str]:
    """Löscht eine Alert-Regel."""
    removed = alert_engine.remove_rule(rule_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert-Regel mit ID '{rule_id}' nicht gefunden.",
        )
    return {"status": "deleted", "id": rule_id}


@app.get("/api/v1/alerts/history", response_model=list[AlertEvent], tags=["Alerts"])
async def list_alert_history() -> list[AlertEvent]:
    """Liefert zuletzt ausgelöste Alert-Events."""
    return list(alert_engine.triggered_alerts)


# -----------------------------------------------------------------------------
# WebSockets
# -----------------------------------------------------------------------------
@app.websocket("/ws/dashboard")
@app.websocket("/ws/live")
async def websocket_dashboard(websocket: WebSocket) -> None:
    """WebSocket-Verbindung für Live-Metriken und Alert-Events."""
    await connection_manager.connect(websocket)
    try:
        while True:
            # Verbindung aktiv halten und eventuelle Ping/Pong oder Befehle empfangen
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket)
    except Exception:  # noqa: BLE001 - Abbruch bei Verbindungsende
        await connection_manager.disconnect(websocket)


# -----------------------------------------------------------------------------
# Statische Dateien & Frontend Mount
# -----------------------------------------------------------------------------
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
