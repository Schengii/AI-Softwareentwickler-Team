"""Haupteinstiegspunkt für den cachegrid_proxy Service."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.engine import get_cache_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan-Handler für Startup- und Shutdown-Prozesse."""
    _settings = get_settings()
    engine = get_cache_engine()
    await engine.start()
    yield
    await engine.stop()


app = FastAPI(
    title="CacheGrid Proxy",
    description="Intelligenter In-Memory- und Disk-Caching-Service mit Thundering-Herd-Schutz",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", summary="Health Check")
async def health_check() -> JSONResponse:
    """Liefert den aktuellen Zustand des Cache-Dienstes."""
    return JSONResponse(status_code=200, content={"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
