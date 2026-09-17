from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.telemetry import router as telemetry_router
from app.api.websocket import router as websocket_router
from app.core.security import setup_security


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup resources can be initialized here
    yield
    # Shutdown resources can be cleaned up here

app = FastAPI(lifespan=lifespan)

# Setup security middlewares as requested by the security team
setup_security(app)

# Include routers
app.include_router(telemetry_router)
app.include_router(websocket_router)

@app.get("/health")
def health():
    return {"status": "ok"}

# Mount frontend static files
app.mount("/", StaticFiles(directory="public", html=True), name="public")
