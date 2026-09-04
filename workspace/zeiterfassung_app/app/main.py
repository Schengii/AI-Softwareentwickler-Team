"""Entry point for FastAPI Zeiterfassungs-App."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, async_session, engine
from .dependencies import get_db
from .routers import auth, time_entries, users

# OpenAPI Metadaten
description = """
Die Zeiterfassungs-API ermöglicht Selbstständigen die effiziente Verwaltung von Projekten und Arbeitszeiten.

### Features
* **Authentifizierung**: JWT-basierter OAuth2-Flow.
* **Projektverwaltung**: CRUD für Kundenprojekte mit Stundensätzen.
* **Zeiterfassung**: Präzise Erfassung von Start/End-Zeitpunkten.
"""

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # Startup: Create DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: Clean up if necessary

app = FastAPI(
    title="Zeiterfassung API",
    version="0.1.0",
    description=description,
    lifespan=lifespan,
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
    ]
)

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

# Dependency override for DB session
app.dependency_overrides[get_db] = async_session
