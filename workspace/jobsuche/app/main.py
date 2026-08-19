# app/main.py
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logger import logger
from app.api import jobs, gdpr

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Jobsuche API",
    version="1.2.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS – nur Frontend‑Domain zulassen
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# Rate‑Limiting (100 req/min pro IP)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# Router einbinden
app.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
app.include_router(gdpr.router, prefix="/gdpr", tags=["GDPR"])

@app.get("/healthz", tags=["Monitoring"])
def health_check():
    """Einfacher Liveness‑Check für Kubernetes / Load‑Balancer."""
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")
