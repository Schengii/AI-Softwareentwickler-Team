"""HyperionSentinel - Core Application Entrypoint.

Hochperformante, ausfallsichere Security- & Traffic-Shaping-Engine.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("hyperionsentinel")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan-Handler fuer Startup und Shutdown."""
    logger.info("Starting HyperionSentinel Engine...")
    # Initialisiere statisches Verzeichnis falls nicht vorhanden
    static_dir = Path("static")
    static_dir.mkdir(parents=True, exist_ok=True)
    index_file = static_dir / "index.html"
    if not index_file.exists():
        index_file.write_text("<!DOCTYPE html><html><body><h1>HyperionSentinel</h1></body></html>", encoding="utf-8")

    yield

    logger.info("Shutting down HyperionSentinel Engine...")


app = FastAPI(
    title="HyperionSentinel",
    version="1.0.0",
    description="Security- & Traffic-Shaping-Engine mit Sliding-Window Rate-Limiting",
    lifespan=lifespan,
)

# Statische Dateien mounten
static_path = Path("static")
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Einfacher Healthcheck-Endpunkt."""
    return {"status": "healthy", "service": "HyperionSentinel"}
