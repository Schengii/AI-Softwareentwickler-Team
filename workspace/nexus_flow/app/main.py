"""Nexus Flow Haupteinstiegspunkt.

FastAPI-Anwendung mit Lifespan-Handler für DB-Initialisierung,
CORS-Middleware und Health-Check-Endpunkten.
"""

from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.db.session import init_db

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan-Handler für Startup und Shutdown der Anwendung."""
    logger.info("Initialisiere Datenbank-Tabellen...")
    await init_db()
    yield
    logger.info("Anwendung wird heruntergefahren...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS-Konfiguration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check():
    """Öffentlicher Health-Check-Endpunkt."""
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


# Statische Assets mounten, falls public-Verzeichnis existiert
if os.path.isdir("public"):
    app.mount("/", StaticFiles(directory="public", html=True), name="public")
elif os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=settings.DEBUG)
