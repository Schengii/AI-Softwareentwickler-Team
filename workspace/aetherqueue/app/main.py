import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import dlq_router
from app.api.routes import router as jobs_router
from app.core.settings import get_settings
from app.db.base import Base
from app.db.session import engine
from app.worker.loop import worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Start worker
    worker_task = asyncio.create_task(worker_loop())
    
    yield
    
    # Shutdown worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    
    # Dispose DB engine
    await engine.dispose()

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

# CORS Middleware (as learned from fleet_telemetry_dashboard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(dlq_router)

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
