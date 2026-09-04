"""Entry point for FastAPI Zeiterfassungs-App."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, async_session, engine
from .dependencies import get_db
from .middleware.pii_filter import PIIFilterMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.security_headers import (
    SecureHeadersMiddleware as SecurityHeadersMiddleware,
)
from .routers import auth, export, invoices, reports, time_entries, users

# OpenAPI Metadaten
description = """
Die Zeiterfassungs-API ermöglicht Selbstständigen die effiziente Verwaltung von Projekten und Arbeitszeiten.

### Features
* **Authentifizierung**: JWT-basierter OAuth2-Flow.
* **Projektverwaltung**: CRUD für Kundenprojekte mit Stundensätzen.
* **Zeiterfassung**: Präzise Erfassung von Start/End-Zeitpunkten.
"""

app = FastAPI(
    title="Zeiterfassung API",
    version="0.1.0",
    description=description,
    contact={
        "name": "Support Team",
        "email": "support@example.com",
    },
    license_info={
        "name": "MIT",
    },
    openapi_tags=[
        {"name": "auth", "description": "Authentifizierung und Token-Management"},
        {"name": "users", "description": "Benutzerverwaltung"},
        {"name": "time", "description": "Operations für Zeiteinträge"},
        {"name": "reports", "description": "Berichte und Analysen"},
        {"name": "invoices", "description": "Rechnungsverwaltung"},
        {"name": "export", "description": "Datenexport"},
    ]
)

# Middleware Integration
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(PIIFilterMiddleware)

# CORS – erlaubt das React-Frontend (localhost:3000) im Development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(time_entries.router, prefix="/time", tags=["time"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
app.include_router(export.router, prefix="/export", tags=["export"])

# Create DB tables on startup (for demo / dev only)
@app.on_event("startup")
async def on_startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Dependency override for DB session
app.dependency_overrides[get_db] = async_session
