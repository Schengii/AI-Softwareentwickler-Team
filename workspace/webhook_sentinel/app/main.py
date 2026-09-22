from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.base import Base
from app.db.session import engine
from app.api.v1.events import router as events_router
from app.api.v1.subscriptions import router as subscriptions_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup if needed

app = FastAPI(title="Webhook Sentinel", lifespan=lifespan)

app.include_router(events_router, prefix="/api/v1")
app.include_router(subscriptions_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "Webhook Sentinel API"}

@app.get("/health")
async def health():
    return {"status": "ok"}
