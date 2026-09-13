# app/main.py
import logging
import time

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="Vortex Engine API")
START_TIME = time.time()

@app.get("/healthz")
def healthz():
    return {
        "status": "healthy",
        "service": "vortex_circuit",
        "uptime_seconds": time.time() - START_TIME
    }

@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    uptime = time.time() - START_TIME
    return f'vortex_uptime_seconds {uptime}\nvortex_circuit_state 0\n'

def _register_routers() -> None:
    try:
        from app.api.v1.circuit_breaker import router as cb_router
        app.include_router(cb_router)
    except ImportError as e:
        logger.warning(f"Circuit Breaker Router konnte nicht geladen werden: {e}")

_register_routers()
