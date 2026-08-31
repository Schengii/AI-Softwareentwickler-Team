import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import anyio

from app.schemas import CheckCreate
from app.monitor.checker import monitor
from app.database import init_db, get_db, CheckHistory

STATIC_DIR = Path(__file__).resolve().parent / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Start background monitor worker
    monitor_task = asyncio.create_task(monitor.run())
    yield
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="API Health Monitor", version="1.0.0", lifespan=lifespan)

# Static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def root_dashboard():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "API Health Monitor is running. Access /docs for API."}

@app.get("/checks")
async def get_checks():
    return list(monitor.checks.values())

@app.post("/checks")
async def create_check(check: CheckCreate):
    return monitor.add_check(check)

@app.delete("/checks/{check_id}")
async def delete_check(check_id: str):
    return {"deleted": monitor.checks.pop(check_id, None) is not None}

@app.get("/checks/{check_id}/history")
async def get_check_history(check_id: str, db: Session = Depends(get_db)):
    def fetch_history():
        return db.query(CheckHistory).filter(CheckHistory.check_id == check_id).all()
    
    return await anyio.to_thread.run_sync(fetch_history)

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    monitor.subscribers.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        monitor.subscribers.discard(websocket)
