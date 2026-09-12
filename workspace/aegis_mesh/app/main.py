"""AegisMesh API Gateway - Primäre FastAPI-Applikation."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.endpoints import router as api_v1_router
from app.core.config import Settings, get_settings
from app.db.session import close_db, init_db
from app.services.rate_limiter import get_rate_limiter

__all__ = ["app", "lifespan"]


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan-Kontextmanager für Initialisierung und Teardown."""
    # DB-Tabellen initialisieren (asynchron via engine.begin())
    await init_db()
    # Rate Limiter Vorbereitung / Cache Warmup
    rate_limiter = get_rate_limiter()
    app_instance.state.rate_limiter = rate_limiter
    yield
    # Aufräumarbeiten
    await close_db()


app = FastAPI(
    title="AegisMesh API Gateway",
    description="Intelligentes Zero-Trust API Rate-Limiting & Abuse-Prevention Gateway",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS-Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "https://localhost"],  # Explizite Whitelist statt "*"
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# API-Router einbinden (ohne doppelten Prefix)
app.include_router(api_v1_router)


@app.get("/healthz", tags=["System"], summary="Healthcheck-Endpunkt")
async def healthz(
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Prüft die Funktionsfähigkeit des Gateways."""
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }


# Statische Dashboard-Dateien mounten falls Verzeichnis vorhanden
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
