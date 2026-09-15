from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # Verhindert MIME-Type Sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Verhindert Clickjacking (Einbetten in Iframes)
        response.headers["X-Frame-Options"] = "DENY"
        
        # Aktiviert XSS-Filter in älteren Browsern
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Erzwingt HTTPS (HSTS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Content Security Policy (CSP)
        # Erlaubt Ressourcen vom eigenen Ursprung, Inline-Scripts/Styles (für Vue/React/Highlight.js oft nötig)
        # und externe Fonts/Styles von cdnjs (für FontAwesome etc.)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdnjs.cloudflare.com; "
            "img-src 'self' data:;"
        )
        response.headers["Content-Security-Policy"] = csp
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response
