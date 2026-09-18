from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.security import setup_security
from app.database import Base, engine
from app.routers import events


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()

app = FastAPI(
    title="AegisFlow",
    description="Event-Broker & Resilienz-Hub",
    version="1.0.0",
    lifespan=lifespan
)

setup_security(app)

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}

@app.get("/api/v1/metrics", tags=["Metrics"])
async def get_metrics():
    return {"success_rate": 1.0, "forwarded_success": 0, "forwarded_failed": 0, "dlq_count": 0}

app.include_router(events.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
