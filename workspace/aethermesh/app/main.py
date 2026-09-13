"""AetherMesh Engine - Hauptanwendung & Lifespan-Management.

Startet den asynchronen Worker-Pool und orchestriert Backpressure,
Priority-Queue, SQLite-Spooling sowie SSE/WebSocket-Endpunkte.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.jobs import router as jobs_router
from app.api.v1.stream import router as stream_router
from app.core.config import get_settings
from app.db.session import init_db
from app.services.backpressure import BackpressureController
from app.services.metrics import MetricsAggregator
from app.services.queue import JobQueueManager
from app.services.worker import WorkerPool

settings = get_settings()

# Globale Service-Singletons für Dependency Injection
backpressure_controller = BackpressureController()
metrics_aggregator = MetricsAggregator()
queue_manager = JobQueueManager(backpressure_controller=backpressure_controller)
worker_pool = WorkerPool(
    queue_manager=queue_manager,
    metrics_aggregator=metrics_aggregator,
    backpressure_controller=backpressure_controller,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan-Kontextmanager für sauberen Startup & Graceful Shutdown."""
    # 1. Datenbanktabellen synchronisieren
    await init_db()

    # 2. Persistente unfertige Jobs aus SQLite in In-Memory-Queue nachladen
    await queue_manager.recover_pending_jobs()

    # 3. Worker-Pool starten
    await worker_pool.start()

    yield

    # 4. Graceful Shutdown des Worker-Pools
    await worker_pool.stop()


app = FastAPI(
    title="AetherMesh Engine",
    description="Intelligente, fehlertolerante Event-Streaming- & Workflow-Orchestrierungs-Engine",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API-Router registrieren (Prefixe nicht doppeln!)
app.include_router(jobs_router)
app.include_router(stream_router)

# Statische Dateien für Dashboard einbinden (falls Verzeichnis existiert)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")


@app.get("/health", tags=["Monitoring"])
async def health_check() -> dict[str, str]:
    """Basis-Gesundheitsprüfung der Engine."""
    return {"status": "ok", "service": "AetherMesh Engine"}
