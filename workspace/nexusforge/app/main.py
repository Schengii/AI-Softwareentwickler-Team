import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.database import Base, engine, get_async_session
from app.repositories.audit_log import audit_log_repo

try:
    from app.core.config import get_settings
    settings = get_settings()
except ImportError:
    class Settings:
        PROJECT_NAME = "API"
        DEBUG = False
    settings = Settings()

# Fallback-Router, falls die echten Module noch nicht existieren
feature_flags_router = APIRouter()
tenants_router = APIRouter()
audit_logs_router = APIRouter()

logger = logging.getLogger(__name__)

async def retention_policy_task():
    """Hintergrund-Task für die Data Retention Policy (DSGVO)."""
    while True:
        try:
            # Hole eine Session aus dem Generator
            gen = get_async_session()
            session = await anext(gen)
            deleted = await audit_log_repo.cleanup_old_logs(session, days=90)
            if deleted > 0:
                logger.info(f"Retention Policy: {deleted} alte AuditLogs gelöscht.")
        except Exception as e:
            logger.error(f"Retention policy error: {e}")
        await asyncio.sleep(86400) # Einmal täglich ausführen

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Datenbank-Tabellen initialisieren
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Retention Policy Task starten
    task = asyncio.create_task(retention_policy_task())
    yield
    # Task beim Shutdown beenden
    task.cancel()

app = FastAPI(
    title=getattr(settings, "PROJECT_NAME", "API"),
    lifespan=lifespan,
    debug=getattr(settings, "DEBUG", False)
)

# Router einbinden (Fix für funktionslose API)
app.include_router(feature_flags_router, prefix="/api/v1/flags", tags=["Feature Flags"])
app.include_router(tenants_router, prefix="/api/v1/tenants", tags=["Tenants"])
app.include_router(audit_logs_router, prefix="/api/v1/audit", tags=["Audit Logs"])

@app.get("/health")
async def health():
    return {"status": "ok"}
