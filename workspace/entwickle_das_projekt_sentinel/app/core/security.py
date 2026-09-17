from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = message.setdefault("headers", [])
                    headers.append((b"x-content-type-options", b"nosniff"))
                    headers.append((b"x-frame-options", b"DENY"))
                    headers.append((b"x-xss-protection", b"1; mode=block"))
                await send(message)
            await self.app(scope, receive, send_wrapper)
        else:
            # For websocket and lifespan, just pass through without modifying headers
            await self.app(scope, receive, send)

def setup_security(app: FastAPI):
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"]
    )
