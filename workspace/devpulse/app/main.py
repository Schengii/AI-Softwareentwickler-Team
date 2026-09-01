from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.api.endpoints import incidents, services

app = FastAPI(title="DevPulse API")

# 1. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion auf spezifische Domains einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Trusted Host Middleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# 3. Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# API v1: incidents.py/services.py wurden bisher nie über include_router() eingebunden - die
# Router existierten im Projekt, waren aber von der eigentlichen App nie erreichbar (jeder
# Aufruf von /api/v1/incidents oder /api/v1/services hätte 404 zurückgegeben). Health-Check
# zusätzlich unter demselben Präfix, da tests/test_api.py exakt /api/v1/health erwartet -
# der bisherige bare /health bleibt für einfache Infra-/Kubernetes-Probes zusätzlich bestehen.
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(incidents.router)
api_v1.include_router(services.router)


@api_v1.get("/health")
async def health_check_v1():
    return {"status": "healthy"}


app.include_router(api_v1)
