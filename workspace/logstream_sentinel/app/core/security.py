"""Security utilities, validation schemas, and middleware for LogStream Sentinel.
"""
import json
import re
from datetime import datetime
from typing import Any

from fastapi import Request, status
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Maximale Payload-Größe: 1 MB für API-Requests
MAX_CONTENT_LENGTH = 1024 * 1024  # 1 MB
# Maximale Metadata-Größe: 64 KB
MAX_METADATA_BYTES = 64 * 1024
# Maximale Message-Länge: 32.768 Zeichen
MAX_MESSAGE_LENGTH = 32768
# Maximale Service-Name-Länge: 128 Zeichen
MAX_SERVICE_NAME_LENGTH = 128

SERVICE_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.\:\/]+$")
ALLOWED_LOG_LEVELS = {"INFO", "WARN", "ERROR", "CRITICAL"}


class SecurityPayloadLimitMiddleware(BaseHTTPMiddleware):
    """Middleware zur Erzwingung von maximalen Payload-Größen (Content-Length / Body-Streaming)."""

    def __init__(self, app, max_bytes: int = MAX_CONTENT_LENGTH):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        # 1. Content-Length Header vorab prüfen falls vorhanden
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length_int = int(content_length)
                if length_int > self.max_bytes:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={
                            "detail": f"Payload zu groß. Maximal erlaubt sind {self.max_bytes} Bytes."
                        },
                    )
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Ungültiger Content-Length Header."},
                )

        # 2. Für mutationsbasierte Requests den Body streamen und Zähler mitführen
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > self.max_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "detail": f"Payload zu groß. Maximal erlaubt sind {self.max_bytes} Bytes."
                    },
                )

        response = await call_next(request)
        return response


class SecureLogCreate(BaseModel):
    """Sicher validiertes Eingabeschema für POST /api/logs."""

    service_name: str = Field(..., min_length=1, max_length=MAX_SERVICE_NAME_LENGTH)
    level: str = Field(..., description="Log-Level: INFO, WARN, ERROR, CRITICAL")
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)
    metadata: dict[str, Any] | None = None
    timestamp: str | None = None

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("service_name darf nicht leer sein.")
        if not SERVICE_NAME_REGEX.match(trimmed):
            raise ValueError(
                "service_name enthält ungültige Zeichen (erlaubt: alphanumerisch, _, -, ., :, /)."
            )
        return trimmed

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        upper_level = v.strip().upper()
        if upper_level not in ALLOWED_LOG_LEVELS:
            raise ValueError(
                f"Ungültiges Log-Level '{v}'. Erlaubt sind: {', '.join(sorted(ALLOWED_LOG_LEVELS))}"
            )
        return upper_level

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        # Null-Bytes verbieten (verhindert Poisoning & String-Truncation)
        if "\x00" in v:
            raise ValueError("message darf keine Null-Bytes enthalten.")
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return None
        # JSON-Serialisierbarkeit & Größenprüfung
        try:
            serialized = json.dumps(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"metadata muss ein valides JSON-Objekt sein: {exc}") from exc

        if len(serialized.encode("utf-8")) > MAX_METADATA_BYTES:
            raise ValueError(
                f"metadata überschreitet die Maximalgröße von {MAX_METADATA_BYTES} Bytes."
            )

        # Prüfung auf gefährliche Rekursionstiefe / Schlüssel
        def check_node(obj, depth=0):
            if depth > 10:
                raise ValueError("metadata überschreitet die maximale Schachtelungstiefe von 10.")
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if not isinstance(key, str):
                        raise ValueError("Alle Schlüssel in metadata müssen Strings sein.")
                    if "\x00" in key:
                        raise ValueError("Schlüssel in metadata dürfen keine Null-Bytes enthalten.")
                    if len(key) > 256:
                        raise ValueError("Schlüssel in metadata darf maximal 256 Zeichen lang sein.")
                    check_node(val, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    check_node(item, depth + 1)

        check_node(v)
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str | None) -> str | None:
        if not v:
            return None
        trimmed = v.strip()
        try:
            ts_str = trimmed.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str)
            # Begrenzung auf plausible Datumsbereiche
            if dt.year < 1970 or dt.year > 2100:
                raise ValueError("timestamp liegt außerhalb des plausiblen Bereichs (1970-2100).")
        except Exception as exc:
            raise ValueError(f"Ungültiges ISO-8601 Timestamp-Format: {trimmed}") from exc
        return trimmed


def sanitize_search_query(query_str: str | None, max_len: int = 200) -> str | None:
    """Bereinigt Such-Strings vor SQL-Statements und filtert Null-Bytes."""
    if not query_str:
        return None
    cleaned = query_str.replace("\x00", "").strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned if cleaned else None
