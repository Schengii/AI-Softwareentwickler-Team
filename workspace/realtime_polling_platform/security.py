import os
from fastapi import FastAPI, Request
from fastapi.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # HSTS: Strict-Transport-Security (1 Jahr)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        # CSP: Content-Security-Policy (Restriktiv)
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; object-src 'none';"
        # X-Frame-Options: Deny
        response.headers["X-Frame-Options"] = "DENY"
        # X-Content-Type-Options: Nosniff
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Referrer-Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

def add_security_middleware(app: FastAPI):
    app.add_middleware(SecurityHeadersMiddleware)
