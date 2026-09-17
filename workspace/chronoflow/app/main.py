from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import app.models.saga  # Ensure models are registered
from app.api.sagas import router as sagas_router
from app.api.sagas import ws_router
from app.db.base import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="ChronoFlow", lifespan=lifespan)

app.include_router(sagas_router)
app.include_router(ws_router)

@app.get("/health")
async def health():
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="public", html=True), name="public")
