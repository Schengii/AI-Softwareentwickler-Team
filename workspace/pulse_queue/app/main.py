from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.database import engine, Base
from app.api import routes_jobs, routes_workers, routes_stats
from app.services.queue_engine import queue_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Start worker
    await queue_engine.start()
    
    yield
    
    # Stop worker
    await queue_engine.stop()
    await engine.dispose()

app = FastAPI(title="pulse_queue", lifespan=lifespan)

app.include_router(routes_jobs.router)
app.include_router(routes_workers.router)
app.include_router(routes_stats.router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
