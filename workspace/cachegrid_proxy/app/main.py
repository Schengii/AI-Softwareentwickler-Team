"""CacheGrid Proxy - Zentraler FastAPI-Einstiegspunkt."""

from contextlib import asynccontextmanager
import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import uvicorn

from app.core.config import get_settings
from app.core.engine import CacheGridEngine

logger = logging.getLogger("cachegrid.main")

# Modul-Level Engine-Instanz für Singleton-Zugriff
engine = CacheGridEngine()


def get_engine() -> CacheGridEngine:
    """Dependency Provider für die CacheGridEngine."""
    return engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan-Handler für sauberes Startup und Graceful Shutdown."""
    logger.info("Starte CacheGrid Proxy Engine...")
    await engine.start()
    app.state.engine = engine
    yield
    logger.info("Stoppe CacheGrid Proxy Engine...")
    await engine.stop()


app = FastAPI(
    title="CacheGrid Proxy",
    description="Hierarchischer In-Memory & Disk Cache mit Mutex-Locking und Tag-Invalidierung",
    version="1.0.0",
    lifespan=lifespan,
)


class CacheSetRequest(BaseModel):
    """Schema für Cache-Schreiboperationen."""

    key: str
    value: Any
    ttl: float | None = None
    tags: list[str] | None = Field(default=None)


class TagInvalidationRequest(BaseModel):
    """Schema für Tag-Invalidierungsoperationen."""

    tags: list[str]
    mode: str = "any"


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health-Check-Endpunkt für Monitoring und Smoke-Tests."""
    return {"status": "ok"}


@app.get("/", tags=["Health"])
async def root() -> dict[str, str]:
    """Root-Endpunkt für Smoke-Tests."""
    return {"status": "ok", "service": "CacheGrid Proxy"}


@app.get("/api/cache/{key}", tags=["Cache"])
async def get_cache_key(
    key: str,
    cache_engine: CacheGridEngine = Depends(get_engine),
) -> dict[str, Any]:
    """Liest einen Eintrag aus RAM oder Disk."""
    val = await cache_engine.get(key)
    if val is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key '{key}' nicht gefunden",
        )
    return {"key": key, "value": val}


@app.post("/api/cache", status_code=status.HTTP_201_CREATED, tags=["Cache"])
async def set_cache_key(
    payload: CacheSetRequest,
    cache_engine: CacheGridEngine = Depends(get_engine),
) -> dict[str, Any]:
    """Speichert einen Eintrag im Cache mit explizitem Audit-Logging."""
    saved = await cache_engine.set(
        key=payload.key,
        value=payload.value,
        ttl=payload.ttl,
        tags=payload.tags,
    )
    logger.info("Cache-Eintrag gesetzt: key=%s, tags=%s", payload.key, payload.tags)
    return {"key": saved.key, "status": "stored"}


@app.delete("/api/cache/{key}", tags=["Cache"])
async def delete_cache_key(
    key: str,
    cache_engine: CacheGridEngine = Depends(get_engine),
) -> dict[str, Any]:
    """Löscht einen Eintrag aus allen Tiers mit explizitem Audit-Logging."""
    deleted = await cache_engine.delete(key)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key '{key}' nicht gefunden",
        )
    logger.info("Cache-Eintrag gelöscht: key=%s", key)
    return {"key": key, "deleted": True}


@app.post("/api/cache/invalidate-tags", tags=["Cache"])
async def invalidate_tags(
    payload: TagInvalidationRequest,
    cache_engine: CacheGridEngine = Depends(get_engine),
) -> dict[str, Any]:
    """Invalidiert Keys selektiv über Tags mit explizitem Audit-Logging."""
    invalidated = await cache_engine.invalidate_by_tags(tags=payload.tags, mode=payload.mode)
    logger.info(
        "Tags invalidiert: tags=%s, mode=%s, count=%d",
        payload.tags,
        payload.mode,
        len(invalidated),
    )
    return {"invalidated_count": len(invalidated), "invalidated_keys": invalidated}


@app.get("/api/stats", tags=["Monitoring"])
async def get_stats(
    cache_engine: CacheGridEngine = Depends(get_engine),
) -> dict[str, Any]:
    """Liefert aggregierte Cache-Statistiken."""
    return await cache_engine.get_stats()


if __name__ == "__main__":
    settings = get_settings()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )
