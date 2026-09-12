from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Hintergrund-Worker hier starten
    yield
    # Hintergrund-Worker hier sauber stoppen

from app.api.endpoints import router as api_router

app = FastAPI(title="HookSentinel", lifespan=lifespan)
app.include_router(api_router, prefix="/api/v1")
