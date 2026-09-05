import logging
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import ALLOWED_CHECK_HOSTS
from app.database import SessionLocal, get_db, init_db
from app.models import EndpointStatus, Task
from app.schemas import EndpointStatusResponse, TaskCreate, TaskResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Erstellt beim Start alle Tabellen, falls sie noch fehlen."""
    init_db()
    yield


app = FastAPI(title="TaskPulse", version="0.1.0", lifespan=lifespan)


@app.get("/")
def read_root():
    return {"message": "TaskPulse API", "docs": "/docs"}


@app.post("/tasks", response_model=TaskResponse)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    """Legt eine neue Hintergrund-Aufgabe an."""
    task = Task(name=payload.name)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks(db: Session = Depends(get_db)):
    """Liefert alle angelegten Aufgaben."""
    return db.query(Task).order_by(Task.id).all()


def _run_status_check(url: str) -> None:
    """Führt den HTTP-Check im Hintergrund aus und speichert das Ergebnis."""
    try:
        with httpx.Client(timeout=5.0) as client:
            start = time.perf_counter()
            response = client.get(url)
            end = time.perf_counter()
        db = SessionLocal()
        try:
            entry = EndpointStatus(
                url=url,
                status_code=response.status_code,
                response_time=round(end - start, 3),
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("Status-Check für %s fehlgeschlagen", url)


@app.post("/status/check")
def trigger_status_check(url: str = Query(..., description="Zu prüfende URL")):
    """Startet einen Status-Check für eine erlaubte URL (Fire-and-forget)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ALLOWED_CHECK_HOSTS:
        raise HTTPException(status_code=400, detail="URL ist nicht erlaubt")
    thread = threading.Thread(target=_run_status_check, args=(url,), daemon=True)
    thread.start()
    return {"message": "Check initiated"}


@app.get("/status", response_model=list[EndpointStatusResponse])
def list_status(db: Session = Depends(get_db)):
    """Liefert die gespeicherten Status-Messungen, neueste zuerst."""
    return db.query(EndpointStatus).order_by(EndpointStatus.id.desc()).all()