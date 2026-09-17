"""EcoTrack AI - Haupteinstiegspunkt der FastAPI-Anwendung."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.fleet import fleet_router
from app.api.health import router as health_router
from app.api.ml_finops import finops_router, ml_router
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan-Handler für Ressourceninitialisierung und Shutdown."""
    # Startup-Logik
    yield
    # Shutdown-Logik


settings = get_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="EcoTrack AI - AI Sustainability & Carbon Fleet Gateway",
    lifespan=lifespan,
)

# CORS-Konfiguration (sicher konfiguriert)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root Health-Check (ohne Auth, zwingend gefordert)
@app.get("/health", tags=["Health"])
async def root_health():
    """Zentraler Health-Check-Endpunkt."""
    return {
        "status": "ok",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


# Router-Registrierung unter /api/v1
app.include_router(health_router, prefix="/api/v1", tags=["Health"])
app.include_router(fleet_router, prefix="/api/v1/fleet", tags=["Fleet"])
app.include_router(ml_router, prefix="/api/v1/predict", tags=["ML Analytics"])
app.include_router(finops_router, prefix="/api/v1/finops", tags=["FinOps"])

# Statische Dateien für Web/PWA-Client mounten, falls Verzeichnis existiert
static_dir = Path("public")
if not static_dir.exists():
    static_dir = Path("static")
    if not static_dir.exists():
        static_dir.mkdir(parents=True, exist_ok=True)
        # Dummy index.html für Fallback anlegen
        index_file = static_dir / "index.html"
        if not index_file.exists():
            index_file.write_text(
                "<!DOCTYPE html><html><head><title>EcoTrack AI</title></head><body><h1>EcoTrack AI Gateway</h1></body></html>",
                encoding="utf-8"
            )

app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
