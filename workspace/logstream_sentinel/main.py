import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, DateTime, Integer, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# --- Datenbank-Setup ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./logs.db")
engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

class LogEntry(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    level = Column(String(20), nullable=False, index=True)
    service_name = Column(String(100), nullable=False, index=True)
    message = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    title = Column(String(255), nullable=False)
    severity = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="OPEN")
    spike_count = Column(Integer, nullable=False)

# --- Pydantic Schemas ---
class LogCreate(BaseModel):
    service_name: str
    level: str
    message: str
    metadata: dict[str, Any] | None = None
    timestamp: str | None = None

class LogResponse(BaseModel):
    id: int
    service_name: str
    level: str
    message: str
    metadata: dict[str, Any] | None = None
    timestamp: str

    model_config = ConfigDict(from_attributes=True)

class IncidentResponse(BaseModel):
    id: int
    timestamp: str
    title: str
    severity: str
    status: str
    spike_count: int

    model_config = ConfigDict(from_attributes=True)

class StatsResponse(BaseModel):
    log_rate_per_minute: float
    error_rate_percent: float
    level_distribution: dict[str, int] = {}
    service_distribution: dict[str, int] = {}
    total_logs: int = 0

# --- WebSocket Verbindungsmanager ---
class ConnectionManager:
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

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            connections = list(self.active_connections)
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001 - Disconnected client
                await self.disconnect(connection)

ws_manager = ConnectionManager()

# --- Spike Detector Background Worker ---
spike_worker_task: asyncio.Task | None = None

async def check_for_error_spikes() -> None:
    """Prüft, ob in den letzten 30 Sekunden mehr als 5 ERROR/CRITICAL-Logs aufgetreten sind."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=30)
    async with async_session_factory() as session:
        query = select(func.count(LogEntry.id)).where(
            LogEntry.level.in_(["ERROR", "CRITICAL"]),
            LogEntry.timestamp >= window_start
        )
        res = await session.execute(query)
        error_count = res.scalar() or 0

        if error_count >= 5:
            recent_incident_query = select(Incident).where(
                Incident.timestamp >= (now - timedelta(seconds=60)),
                Incident.status == "OPEN"
            )
            recent_incidents = (await session.execute(recent_incident_query)).scalars().all()
            if not recent_incidents:
                new_incident = Incident(
                    title=f"Error Spike erkannt: {error_count} Fehler in 30s",
                    severity="CRITICAL",
                    status="OPEN",
                    spike_count=error_count,
                    timestamp=now
                )
                session.add(new_incident)
                await session.commit()
                await session.refresh(new_incident)
                await ws_manager.broadcast({
                    "event": "new_incident",
                    "data": {
                        "id": new_incident.id,
                        "title": new_incident.title,
                        "severity": new_incident.severity,
                        "status": new_incident.status,
                        "spike_count": new_incident.spike_count,
                        "timestamp": new_incident.timestamp.isoformat()
                    }
                })

async def spike_detector_loop() -> None:
    while True:
        try:
            await asyncio.sleep(5)
            await check_for_error_spikes()
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 - Worker soll im Fehlerfall weiterlaufen
            await asyncio.sleep(5)

# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global spike_worker_task
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    spike_worker_task = asyncio.create_task(spike_detector_loop())
    yield
    if spike_worker_task:
        spike_worker_task.cancel()
        try:
            await spike_worker_task
        except asyncio.CancelledError:
            pass
    await engine.dispose()

app = FastAPI(
    title="LogStream Sentinel",
    description="Hochperformante Log-Streaming- und Analyse-Plattform",
    version="1.0.0",
    lifespan=lifespan
)

# Statische Dateien mounten
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=FileResponse)
async def root():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"message": "LogStream Sentinel API"}

@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "LogStream Sentinel"}

# --- API Endpunkte ---

@app.post("/api/logs", status_code=status.HTTP_201_CREATED, response_model=LogResponse)
async def post_logs(payload: LogCreate):
    parsed_time = None
    if payload.timestamp:
        try:
            ts_str = payload.timestamp.replace("Z", "+00:00")
            parsed_time = datetime.fromisoformat(ts_str)
        except Exception:  # noqa: BLE001
            parsed_time = datetime.now(timezone.utc)
    else:
        parsed_time = datetime.now(timezone.utc)

    metadata_str = json.dumps(payload.metadata) if payload.metadata is not None else None

    entry = LogEntry(
        service_name=payload.service_name,
        level=payload.level.upper(),
        message=payload.message,
        metadata_json=metadata_str,
        timestamp=parsed_time
    )

    async with async_session_factory() as session:
        session.add(entry)
        await session.commit()
        await session.refresh(entry)

    response_data = LogResponse(
        id=entry.id,
        service_name=entry.service_name,
        level=entry.level,
        message=entry.message,
        metadata=payload.metadata,
        timestamp=entry.timestamp.isoformat()
    )

    await ws_manager.broadcast({
        "event": "new_log",
        "data": response_data.model_dump()
    })

    return response_data

@app.get("/api/logs", response_model=list[LogResponse])
async def get_logs(
    level: str | None = Query(None, description="Log Level Filter"),
    service_name: str | None = Query(None, description="Service Name Filter"),
    search: str | None = Query(None, description="Volltextsuche in message"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    async with async_session_factory() as session:
        query = select(LogEntry)

        if level:
            query = query.where(LogEntry.level == level.upper())
        if service_name:
            query = query.where(LogEntry.service_name == service_name)
        if search:
            query = query.where(LogEntry.message.contains(search))

        query = query.order_by(LogEntry.timestamp.desc()).offset(offset).limit(limit)
        result = await session.execute(query)
        logs = result.scalars().all()

        output = []
        for l in logs:
            meta = json.loads(l.metadata_json) if l.metadata_json else None
            output.append(LogResponse(
                id=l.id,
                service_name=l.service_name,
                level=l.level,
                message=l.message,
                metadata=meta,
                timestamp=l.timestamp.isoformat() if l.timestamp else datetime.now(timezone.utc).isoformat()
            ))
        return output

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    async with async_session_factory() as session:
        total_res = await session.execute(select(func.count(LogEntry.id)))
        total_logs = total_res.scalar() or 0

        now = datetime.now(timezone.utc)
        one_min_ago = now - timedelta(minutes=1)
        recent_res = await session.execute(
            select(func.count(LogEntry.id)).where(LogEntry.timestamp >= one_min_ago)
        )
        logs_last_minute = recent_res.scalar() or 0

        error_res = await session.execute(
            select(func.count(LogEntry.id)).where(LogEntry.level.in_(["ERROR", "CRITICAL"]))
        )
        total_errors = error_res.scalar() or 0

        error_rate = (total_errors / total_logs * 100.0) if total_logs > 0 else 0.0

        level_res = await session.execute(
            select(LogEntry.level, func.count(LogEntry.id)).group_by(LogEntry.level)
        )
        level_dist = {row[0]: row[1] for row in level_res.all()}

        service_res = await session.execute(
            select(LogEntry.service_name, func.count(LogEntry.id)).group_by(LogEntry.service_name)
        )
        service_dist = {row[0]: row[1] for row in service_res.all()}

        return StatsResponse(
            log_rate_per_minute=float(logs_last_minute),
            error_rate_percent=round(error_rate, 2),
            level_distribution=level_dist,
            service_distribution=service_dist,
            total_logs=total_logs
        )

@app.delete("/api/logs")
async def delete_logs(
    retention_minutes: int | None = Query(None, ge=1),
    hours: int | None = Query(None, ge=1)
):
    now = datetime.now(timezone.utc)
    if retention_minutes is not None:
        cutoff = now - timedelta(minutes=retention_minutes)
    elif hours is not None:
        cutoff = now - timedelta(hours=hours)
    else:
        cutoff = now - timedelta(hours=24)

    async with async_session_factory() as session:
        stmt = delete(LogEntry).where(LogEntry.timestamp < cutoff)
        res = await session.execute(stmt)
        await session.commit()
        deleted_count = res.rowcount

    return {"message": "Logs erfolgreich bereinigt", "deleted_count": deleted_count, "status": "deleted"}

@app.get("/api/incidents", response_model=list[IncidentResponse])
async def get_incidents(
    status: str | None = Query(None, description="Filter nach Status OPEN oder RESOLVED")
):
    async with async_session_factory() as session:
        query = select(Incident)
        if status:
            query = query.where(Incident.status == status.upper())
        query = query.order_by(Incident.timestamp.desc())
        res = await session.execute(query)
        incidents = res.scalars().all()

        return [
            IncidentResponse(
                id=inc.id,
                timestamp=inc.timestamp.isoformat() if inc.timestamp else datetime.now(timezone.utc).isoformat(),
                title=inc.title,
                severity=inc.severity,
                status=inc.status,
                spike_count=inc.spike_count
            )
            for inc in incidents
        ]

@app.post("/api/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: int):
    async with async_session_factory() as session:
        query = select(Incident).where(Incident.id == incident_id)
        res = await session.execute(query)
        inc = res.scalar_one_or_none()
        if not inc:
            raise HTTPException(status_code=404, detail="Incident nicht gefunden")
        inc.status = "RESOLVED"
        await session.commit()
        return {"message": f"Incident {incident_id} als RESOLVED markiert"}

@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:  # noqa: BLE001
        await ws_manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
