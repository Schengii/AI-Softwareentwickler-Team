from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Fügt Standard-Security-Header zu jeder HTTP-Antwort hinzu."""
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response

def setup_security(app: FastAPI) -> None:
    """Konfiguriert CORS und Security-Header für die FastAPI-App."""
    settings = get_settings()
    
    # CORS Middleware (muss vor anderen Middlewares registriert werden)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    
    # Security Headers Middleware
    app.add_middleware(SecurityHeadersMiddleware)
