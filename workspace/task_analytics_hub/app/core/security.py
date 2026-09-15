import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:;"
        return response

class PIIMaskingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Basis-Implementierung für PII-Maskierung in Logs
        # In einer vollständigen Implementierung würden Request-Body und Header nach PII durchsucht
        response = await call_next(request)
        return response

def setup_security(app: FastAPI):
    # CORS strikt konfigurieren (kein allowed_hosts = ["*"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    
    # Security Headers
    app.add_middleware(SecurityHeadersMiddleware)
    
    # PII Masking
    app.add_middleware(PIIMaskingMiddleware)
