"""ChronosLedger Haupt-Einstiegspunkt für FastAPI."""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.gdpr import router as gdpr_router
from app.api.v1.ledger import router as ledger_router
from app.core.config import get_settings
from app.core.db import close_db, init_db
from app.services.buffer import ring_buffer_service

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan-Kontextmanager für Datenbank-Initialisierung und Ring-Buffer-Worker."""
    # 1. Datenbank-Tabellen asynchron erstellen
    await init_db()
    # 2. Asynchronen Batch-Flush Worker starten
    await ring_buffer_service.start()
    try:
        yield
    finally:
        # 3. Ring-Buffer sicher leeren (Drain) und Worker stoppen
        await ring_buffer_service.stop()
        # 4. DB Engine schließen
        await close_db()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Revisionssicheres Audit- & Incident-Logging-Gateway mit SHA-256 Hashverkettung, Ring-Buffer & PII-Maskierung",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API-Router registrieren
app.include_router(ledger_router)
app.include_router(gdpr_router)


@app.get("/health", tags=["System"])
@app.get("/healthz", tags=["System"])
async def health_check() -> dict[str, str]:
    """Health-Check-Endpunkt für Monitoring, Liveness- & Readiness-Probes."""
    return {"status": "ok", "service": settings.PROJECT_NAME, "version": settings.VERSION}


# Falls statisches Frontend vorhanden ist, unter / mounten
public_dir = os.path.join(os.getcwd(), "public")
if os.path.isdir(public_dir):
    app.mount("/", StaticFiles(directory=public_dir, html=True), name="public")
