from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.security import setup_security
from app.routers.events import router as events_router
from app.storage.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: Dispose engine
    await engine.dispose()


app = FastAPI(
    title="AegisFlow",
    description="High-Throughput Event Ingestion Broker with Idempotency and DLQ",
    version="0.1.0",
    lifespan=lifespan,
)

# Setup Security & Resilience Middlewares
setup_security(app)

# Include Routers
app.include_router(events_router)


# Static files and frontend UI
static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "AegisFlow is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
