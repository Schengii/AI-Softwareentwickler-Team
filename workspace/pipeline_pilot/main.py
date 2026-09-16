import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db_session, init_db
from app.engine.executor import execution_engine
from app.schemas import (
    PipelineCreate,
    PipelineResponse,
    PipelineRunResponse,
    StatsResponse,
)
from app.services.pipeline_service import PipelineService
from app.services.run_service import RunService

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan-Handler für DB-Initialisierung und Task-Cleanup."""
    await init_db()
    # Initialisiere statisches Verzeichnis falls nicht existent
    os.makedirs("static", exist_ok=True)
    index_path = os.path.join("static", "index.html")
    if not os.path.exists(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html><head><title>PipelinePilot</title></head><body><h1>PipelinePilot Dashboard</h1></body></html>")
    yield
    # Shutdown: Laufende In-Memory-Tasks abbrechen
    await execution_engine.shutdown()

app = FastAPI(
    title="PipelinePilot",
    description="Entwicklerfreundliche, lokale CI/CD- und Task-Workflow-Engine",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware (Sicher konfiguriert)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health-Check Endpunkt (ohne Authentifizierung)
@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "PipelinePilot"}

# --- Pipeline Endpunkte ---

@app.get("/api/pipelines", response_model=list[PipelineResponse], tags=["Pipelines"])
async def get_pipelines(session: AsyncSession = Depends(get_db_session)):
    service = PipelineService(session)
    return await service.list_pipelines()

@app.post("/api/pipelines", response_model=PipelineResponse, status_code=201, tags=["Pipelines"])
async def create_pipeline(pipeline_in: PipelineCreate, session: AsyncSession = Depends(get_db_session)):
    service = PipelineService(session)
    return await service.create_pipeline(pipeline_in)

@app.get("/api/pipelines/{pipeline_id}", response_model=PipelineResponse, tags=["Pipelines"])
async def get_pipeline(pipeline_id: int, session: AsyncSession = Depends(get_db_session)):
    service = PipelineService(session)
    pipeline = await service.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} nicht gefunden")
    return pipeline

@app.delete("/api/pipelines/{pipeline_id}", tags=["Pipelines"])
async def delete_pipeline(pipeline_id: int, session: AsyncSession = Depends(get_db_session)):
    service = PipelineService(session)
    success = await service.delete_pipeline(pipeline_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} nicht gefunden")
    return {"message": f"Pipeline {pipeline_id} erfolgreich gelöscht", "id": pipeline_id}

@app.post("/api/pipelines/{pipeline_id}/run", response_model=PipelineRunResponse, status_code=202, tags=["Executions"])
async def run_pipeline(
    pipeline_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    service = PipelineService(session)
    pipeline = await service.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} nicht gefunden")

    run_service = RunService(session)
    run = await run_service.create_run(pipeline)
    
    # Asynchrone Ausführung über die ExecutionEngine starten
    await execution_engine.trigger_run(run.id, pipeline.steps)
    
    # Frischen Status des Runs laden
    run_with_steps = await run_service.get_run(run.id)
    return run_with_steps

# --- Run & Execution Endpunkte ---

@app.get("/api/pipelines/{pipeline_id}/runs", response_model=list[PipelineRunResponse], tags=["Executions"])
async def get_pipeline_runs(pipeline_id: int, session: AsyncSession = Depends(get_db_session)):
    service = PipelineService(session)
    pipeline = await service.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} nicht gefunden")

    run_service = RunService(session)
    return await run_service.get_pipeline_runs(pipeline_id)

@app.get("/api/runs", response_model=list[PipelineRunResponse], tags=["Executions"])
async def list_runs(session: AsyncSession = Depends(get_db_session)):
    run_service = RunService(session)
    return await run_service.list_all_runs()

@app.get("/api/runs/{run_id}", response_model=PipelineRunResponse, tags=["Executions"])
async def get_run(run_id: int, session: AsyncSession = Depends(get_db_session)):
    run_service = RunService(session)
    run = await run_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Pipeline-Run {run_id} nicht gefunden")
    return run

@app.post("/api/runs/{run_id}/cancel", tags=["Executions"])
async def cancel_run(run_id: int, session: AsyncSession = Depends(get_db_session)):
    run_service = RunService(session)
    run = await run_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Pipeline-Run {run_id} nicht gefunden")
    
    if run.status in ["SUCCESS", "FAILED", "CANCELLED"]:
        return {"message": f"Run {run_id} ist bereits beendet ({run.status})", "status": run.status}

    cancelled = await execution_engine.cancel_run(run_id)
    # Datenbankstatus aktualisieren
    await run_service.mark_run_cancelled(run_id)
    return {"message": f"Run {run_id} erfolgreich abgebrochen", "status": "CANCELLED", "cancelled_active_task": cancelled}

# --- Stats Endpunkt ---

@app.get("/api/stats", response_model=StatsResponse, tags=["Metrics"])
async def get_stats(session: AsyncSession = Depends(get_db_session)):
    run_service = RunService(session)
    return await run_service.get_stats()

# --- Statische Dateien & Frontend-Mounting ---

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", tags=["Frontend"])
async def serve_dashboard():
    index_file = os.path.join("static", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "PipelinePilot API online. Frontend index.html nicht gefunden."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
