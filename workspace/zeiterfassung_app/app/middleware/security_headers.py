# app/middleware/security_headers.py
from starlette.types import ASGIApp, Receive, Scope, Send


class SecureHeadersMiddleware:
    """Adds OWASP‑recommended security headers to every response."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                # Strict‑Transport‑Security (nur über HTTPS)
                headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains; preload"))
                # X‑Content‑Type‑Options
                headers.append((b"x-content-type-options", b"nosniff"))
                # X‑Frame‑Options
                headers.append((b"x-frame-options", b"SAMEORIGIN"))
                # Referrer‑Policy
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                # Content‑Security‑Policy (nur erlaubte Quellen)
                csp = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; "
                    "font-src 'self'; "
                    "connect-src 'self'; "
                    "frame-ancestors 'self';"
                )
                headers.append((b"content-security-policy", csp.encode()))
                # X‑XSS‑Protection (deaktiviert, weil CSP besser)
                headers.append((b"x-xss-protection", b"0"))
            await send(message)

        await self.app(scope, receive, send_wrapper)
