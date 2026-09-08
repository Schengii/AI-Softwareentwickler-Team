from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import APIKeyHeader

from app.core.config import settings

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def create_app() -> FastAPI:
    app = FastAPI(title=settings.PROJECT_NAME)

    # 1. TrustedHostMiddleware (Schutz gegen Host-Header-Injection)
    app.add_middleware(
        TrustedHostMiddleware, 
        allowed_hosts=settings.ALLOWED_HOSTS
    )

    # 2. CORSMiddleware (Explizite Whitelist)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://{host}" for host in settings.ALLOWED_HOSTS],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    return app

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

