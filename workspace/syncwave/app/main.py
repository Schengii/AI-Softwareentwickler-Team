import html
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import Base, engine, get_async_session
from app.models.log import LogEntry


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001 - Ignore dead connections during broadcast
                pass

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: Dispose engine
    await engine.dispose()

app = FastAPI(title="SyncWave API", lifespan=lifespan)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

class LogCreate(BaseModel):
    level: str = Field(..., pattern="^(INFO|WARN|ERROR|DEBUG|FATAL)$")
    service_name: str = Field(..., max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    payload: str | None = Field(None, max_length=10000)

    @field_validator('payload', 'service_name', mode='before')
    @classmethod
    def sanitize_input(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return html.escape(v)
        return v

class LogResponse(LogCreate):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True

@app.post("/api/logs", response_model=LogResponse)
async def create_log(log_in: LogCreate, db: AsyncSession = Depends(get_async_session)):
    new_log = LogEntry(
        level=log_in.level,
        service_name=log_in.service_name,
        payload=log_in.payload
    )
    db.add(new_log)
    await db.commit()
    await db.refresh(new_log)
    
    # Broadcast to websockets
    await manager.broadcast({
        "id": new_log.id,
        "level": new_log.level,
        "service_name": new_log.service_name,
        "payload": new_log.payload,
        "timestamp": new_log.timestamp.isoformat() if new_log.timestamp else None
    })
    
    return new_log

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """
    WebSocket endpoint for live log streaming.
    Client state: None required.
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, wait for client messages if any
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Mount static files last to avoid catching API routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")
