"""FastAPI-Haupteinstiegspunkt für ToggleForge mit Security-Hardening."""

import json
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import Response as FastAPIResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.endpoints import health_check
from app.api.endpoints import router as api_router
from app.config import get_settings
from app.db import close_db, init_db

settings = get_settings()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Fügt sicherheitsrelevante HTTP-Header zu allen Antworten hinzu."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
        return response


def _mask_pii_value(key: str, value: Any) -> Any:
    """Maskiert personenbezogene Daten (email, name, address)."""
    if isinstance(value, str):
        lower_key = key.lower()
        if "email" in lower_key and "@" in value:
            parts = value.split("@", 1)
            local = parts[0]
            masked_local = (local[0] + "***" + local[-1]) if len(local) > 2 else "***"
            return f"{masked_local}@{parts[1]}"
        if "name" in lower_key and lower_key not in ("app_name", "flag_name", "schema_name"):
            return re.sub(r"\b(\w)\w+", r"\1***", value)
        if "address" in lower_key:
            return "***[REDACTED_ADDRESS]***"
    elif isinstance(value, dict):
        return {k: _mask_pii_value(k, v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_mask_pii_value(key, item) for item in value]
    return value


class PIIMaskingMiddleware(BaseHTTPMiddleware):
    """Prüft API-Responses auf PII und maskiert Felder wie email, name, address wenn gefordert."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)

        # Prüfe, ob PII-Maskierung aktiv ist (via Header, Query-Param oder für sensible Endpunkte)
        mask_requested = (
            request.headers.get("X-Mask-PII", "").lower() in ("true", "1")
            or request.query_params.get("mask_pii", "").lower() in ("true", "1")
            or request.url.path.startswith(settings.API_V1_PREFIX)
        )

        content_type = response.headers.get("content-type", "")
        if mask_requested and "application/json" in content_type:
            try:
                body_bytes = [chunk async for chunk in response.body_iterator]
                body_text = b"".join(body_bytes).decode("utf-8")
                parsed_json = json.loads(body_text)
                if isinstance(parsed_json, dict):
                    masked_json = {k: _mask_pii_value(k, v) for k, v in parsed_json.items()}
                elif isinstance(parsed_json, list):
                    masked_json = [_mask_pii_value("item", item) for item in parsed_json]
                else:
                    masked_json = parsed_json

                new_content = json.dumps(masked_json).encode("utf-8")
                return FastAPIResponse(
                    content=new_content,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type="application/json",
                )
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                # Falls Payload kein valides JSON ist, gebe unveränderte Response zurück
                return response

        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan-Kontextmanager für DB-Initialisierung und Cleanup."""
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="ToggleForge",
    description="Produktionsreifes Feature-Flag- und Dynamic-Configuration-Gateway mit Consistent Hashing",
    version="1.0.0",
    lifespan=lifespan,
)

# 1. Host-Header Validierung: Explizite Host-Whitelist (kein '*')
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "testserver", "toggleforge.internal"],
)

# 2. HTTP Security Header Middleware
app.add_middleware(SecurityHeadersMiddleware)

# 3. PII-Masking Middleware
app.add_middleware(PIIMaskingMiddleware)

# 4. CORS-Konfiguration mit strikter Whitelist statt Wildcards
ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Mask-PII", "Accept"],
    max_age=600,
)

# Direkter Health-Check auf Root-Ebene
app.add_api_route("/health", health_check, methods=["GET"], tags=["Health"])

# API Router einbinden
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Statische Dateien einbinden
static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        """Dashboard Startseite bereitstellen."""
        index_path = static_dir / "index.html"
        return FileResponse(index_path)
