from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # 1. HTTP Smuggling Prevention: ASGI servers handle most, but we can ensure headers are clean
        # Remove potentially malicious headers from the client if we are the edge
        # In a real scenario, we'd check against a list of trusted proxies.
        # Here we sanitize X-Forwarded-* headers to prevent spoofing.
        
        # We can't easily mutate request.headers directly in Starlette as they are immutable.
        # But we can create a new scope and pass it down, or just handle it in the route.
        # Actually, modifying the scope is the standard way in ASGI.
        
        headers = dict(request.scope["headers"])
        
        # Remove spoofed X-Forwarded headers
        headers_to_remove = [
            b"x-forwarded-for", 
            b"x-forwarded-proto", 
            b"x-forwarded-host",
            b"x-forwarded-port"
        ]
        
        cleaned_headers = [(k, v) for k, v in headers.items() if k.lower() not in headers_to_remove]
        
        # Set real values based on the actual connection
        client_ip = request.client.host if request.client else "127.0.0.1"
        client_port = str(request.client.port).encode() if request.client else b"80"
        scheme = request.url.scheme.encode()
        host = request.url.hostname.encode() if request.url.hostname else b"localhost"
        
        cleaned_headers.extend([
            (b"x-forwarded-for", client_ip.encode()),
            (b"x-forwarded-proto", scheme),
            (b"x-forwarded-host", host),
            (b"x-forwarded-port", client_port),
        ])
        
        request.scope["headers"] = cleaned_headers
        
        response = await call_next(request)
        
        # Add security headers to response
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response
