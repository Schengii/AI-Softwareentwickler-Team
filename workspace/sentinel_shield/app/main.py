from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
from app.core.config import get_settings
from app.api import routes_gateway, routes_admin, routes_metrics
from app.models.schemas import HealthResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(
    title="Sentinel Shield",
    lifespan=lifespan
)

settings = get_settings()

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(set(settings.ALLOWED_HOSTS + ["testserver"]))
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok")

app.include_router(routes_gateway.router, prefix="/api/v1", tags=["gateway"])
app.include_router(routes_admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(routes_metrics.router, prefix="/api/v1", tags=["metrics"])
