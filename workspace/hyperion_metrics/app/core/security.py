"""Security-Module für hyperion_metrics.

Enthält Rate-Limiting, Security Headers Middleware, Input-Validation-Helfer,
WebSocket-DoS-Schutz und PII-Maskierung.
"""

from __future__ import annotations

import html
import re
import time
from collections import defaultdict, deque
from typing import Any, Callable
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.websockets import WebSocket, WebSocketDisconnect

# -----------------------------------------------------------------------------
# Konfigurationskonstanten für Sicherheit & DoS-Schutz
# -----------------------------------------------------------------------------
DEFAULT_RATE_LIMIT_REQUESTS = 200  # Max Anfragen pro Zeitfenster
DEFAULT_RATE_LIMIT_WINDOW = 60.0  # Zeitfenster in Sekunden (sliding window)
MAX_REQUEST_BODY_SIZE = 1_048_576  # 1 MB Limit gegen Memory-Exhaustion DoS
MAX_WS_CONNECTIONS_PER_IP = 10  # Max WebSocket-Verbindungen pro Client-IP
MAX_TOTAL_WS_CONNECTIONS = 500  # Globale Obergrenze aktiver WebSocket-Clients
MAX_WS_MESSAGE_SIZE = 65_536  # 64 KB Max WebSocket Frame/Message Payload
MAX_WS_MESSAGES_PER_SECOND = 20  # WebSocket Message Rate Limit pro Client

# Sicherheitsrelevante Regex-Muster zur Validierung
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_\.\:\-]+$")
PII_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PII_IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PII_KEY_PATTERN = re.compile(r"(?i)(api[_-]?key|secret|token|password|auth|bearer)")


# -----------------------------------------------------------------------------
# PII-Maskierung
# -----------------------------------------------------------------------------
def mask_pii(text: str) -> str:
    """Maskiert sensible PII wie E-Mails, Tokens und IPs für sicheres Logging."""
    if not isinstance(text, str):
        return str(text)
    
    # E-Mails maskieren (z.B. j***@example.com)
    def _mask_email(match: re.Match) -> str:
        addr = match.group(0)
        parts = addr.split("@")
        if len(parts) == 2 and len(parts[0]) > 1:
            masked_name = parts[0][0] + "***" + parts[0][-1] if len(parts[0]) > 2 else parts[0][0] + "***"
            return f"{masked_name}@{parts[1]}"
        return "***@***.***"

    masked = PII_EMAIL_PATTERN.sub(_mask_email, text)
    return masked


def mask_sensitive_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Maskiert sensible Werte in Dictionaries (z.B. Passwörter, API-Keys)."""
    sanitized: dict[str, Any] = {}
    for k, v in data.items():
        if PII_KEY_PATTERN.search(k):
            sanitized[k] = "********"
        elif isinstance(v, dict):
            sanitized[k] = mask_sensitive_dict(v)
        elif isinstance(v, str):
            sanitized[k] = mask_pii(v)
        else:
            sanitized[k] = v
    return sanitized


# -----------------------------------------------------------------------------
# Input Validation & Sanitization
# -----------------------------------------------------------------------------
def validate_identifier(value: str, field_name: str = "identifier", max_length: int = 128) -> str:
    """Validiert Metriknamen, Alert-Namen und Tag-Keys gegen Injection/Path-Traversal."""
    if not value or not isinstance(value, str):
        raise ValueError(f"Ungültiger {field_name}: Darf nicht leer sein.")
    
    clean_val = value.strip()
    if len(clean_val) > max_length:
        raise ValueError(f"{field_name} überschreitet maximale Länge von {max_length} Zeichen.")

    if not SAFE_IDENTIFIER_PATTERN.match(clean_val):
        raise ValueError(
            f"Ungültige Zeichen in {field_name} ('{clean_val}'). Nur alphanumerisch, '.', '_', ':', '-' erlaubt."
        )

    # Path-Traversal Prüfung
    if ".." in clean_val or "/" in clean_val or "\\" in clean_val:
        raise ValueError(f"Unerlaubte Pfadzeichen in {field_name}.")

    return clean_val


def sanitize_string(value: str, max_length: int = 256) -> str:
    """Entfernt gefährliche Steuerzeichen und escaped HTML zur XSS-Prävention."""
    if not isinstance(value, str):
        return ""
    trimmed = value.strip()[:max_length]
    # Steuerzeichen entfernen (außer Tab, Newline)
    clean = "".join(ch for ch in trimmed if ch in ("\t", "\n", "\r") or (ord(ch) >= 32 and ord(ch) != 127))
    return html.escape(clean)


# -----------------------------------------------------------------------------
# In-Memory Rate Limiter (Token-Bucket / Sliding Window mit time.monotonic)
# -----------------------------------------------------------------------------
class SlidingWindowRateLimiter:
    """Sliding-Window In-Memory Rate-Limiter basierend auf time.monotonic()."""

    def __init__(self, max_requests: int = DEFAULT_RATE_LIMIT_REQUESTS, window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._history: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, client_key: str) -> tuple[bool, int, float]:
        """Prüft, ob der Request zulässig ist.

        Gibt (is_allowed, remaining_requests, retry_after_seconds) zurück.
        """
        now = time.monotonic()
        history = self._history[client_key]
        cutoff = now - self.window_seconds

        # Veraltete Zeitstempel verwerfen
        while history and history[0] < cutoff:
            history.popleft()

        if len(history) < self.max_requests:
            history.append(now)
            remaining = self.max_requests - len(history)
            return True, remaining, 0.0

        # Limit erreicht
        oldest = history[0]
        retry_after = max(0.1, (oldest + self.window_seconds) - now)
        return False, 0, round(retry_after, 2)

    def cleanup(self) -> None:
        """Entfernt inaktive Client-Einträge zur Speicherfreigabe."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        keys_to_delete: list[str] = []
        for key, history in self._history.items():
            while history and history[0] < cutoff:
                history.popleft()
            if not history:
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del self._history[key]


# Globale Singleton-Instanz für API Rate Limiting
api_rate_limiter = SlidingWindowRateLimiter()


def get_client_ip(request: Request) -> str:
    """Ermittelt die Client-IP unter Beachtung vertrauenswürdiger Header."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Ersten Eintrag nehmen
        ip = forwarded.split(",")[0].strip()
        if ip:
            return ip
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


# -----------------------------------------------------------------------------
# Security Headers & Body-Size Middleware
# -----------------------------------------------------------------------------
class SecurityHeadersAndDoSProtectionMiddleware(BaseHTTPMiddleware):
    """FastAPI Middleware für HTTP-Security-Header, Payload-Limits und Rate-Limiting."""

    def __init__(
        self,
        app: Any,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        max_body_size: int = MAX_REQUEST_BODY_SIZE,
        allowed_hosts: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.rate_limiter = rate_limiter or api_rate_limiter
        self.max_body_size = max_body_size
        self.allowed_hosts = allowed_hosts or ["*"]  # Spezifische Hosts konfigurierbar

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        client_ip = get_client_ip(request)

        # 1. Content-Length Prüfung gegen DoS / Memory Exhaustion
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > self.max_body_size:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Payload Too Large. Maximal {self.max_body_size} Bytes erlaubt."},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Ungültiger Content-Length Header."},
                )

        # 2. Rate-Limiting für zustandsverändernde oder hochfrequente Endpunkte
        # Exclude Health-Check vom strikten Rate-Limiting
        if not request.url.path.startswith("/health"):
            allowed, remaining, retry_after = self.rate_limiter.is_allowed(client_ip)
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests. Bitte Rate-Limit einhalten."},
                )
                response.headers["Retry-After"] = str(int(retry_after) + 1)
                response.headers["X-RateLimit-Limit"] = str(self.rate_limiter.max_requests)
                response.headers["X-RateLimit-Remaining"] = "0"
                self._apply_security_headers(response)
                return response

        # 3. Anfrage an den Handler weitergeben
        response: Response = await call_next(request)

        # 4. Security-Header setzen
        self._apply_security_headers(response)
        return response

    @staticmethod
    def _apply_security_headers(response: Response) -> None:
        """Injiziert defensive HTTP-Security-Header nach OWASP-Empfehlungen."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
        
        # CSP (Content Security Policy) für Dashboard & API
        # Erlaubt Inline-Styles und WebSockets zu 'self'
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )


# -----------------------------------------------------------------------------
# WebSocket-DoS-Schutz & Connection Guard
# -----------------------------------------------------------------------------
class WebSocketSecurityGuard:
    """Verwaltet Verbindungsanzahlen, Message-Größen und Rate-Limits für WebSockets."""

    def __init__(
        self,
        max_connections_per_ip: int = MAX_WS_CONNECTIONS_PER_IP,
        max_total_connections: int = MAX_TOTAL_WS_CONNECTIONS,
        max_message_size: int = MAX_WS_MESSAGE_SIZE,
        max_messages_per_second: int = MAX_WS_MESSAGES_PER_SECOND,
    ) -> None:
        self.max_connections_per_ip = max_connections_per_ip
        self.max_total_connections = max_total_connections
        self.max_message_size = max_message_size
        self.max_messages_per_second = max_messages_per_second

        self._active_connections_per_ip: dict[str, int] = defaultdict(int)
        self._total_active_connections: int = 0
        self._client_message_history: dict[str, deque[float]] = defaultdict(deque)

    def can_connect(self, client_ip: str) -> tuple[bool, str]:
        """Prüft, ob eine neue WebSocket-Verbindung akzeptiert werden darf."""
        if self._total_active_connections >= self.max_total_connections:
            return False, "Server-WebSocket-Kapazitätsgrenze erreicht."
        
        if self._active_connections_per_ip[client_ip] >= self.max_connections_per_ip:
            return False, f"Maximal {self.max_connections_per_ip} gleichzeitige WebSocket-Verbindungen pro IP erlaubt."

        return True, ""

    def register_connection(self, client_ip: str) -> None:
        """Registriert eine erfolgreich geöffnete Verbindung."""
        self._active_connections_per_ip[client_ip] += 1
        self._total_active_connections += 1

    def unregister_connection(self, client_ip: str) -> None:
        """Deregistriert eine geschlossene Verbindung."""
        if self._active_connections_per_ip[client_ip] > 0:
            self._active_connections_per_ip[client_ip] -= 1
        if self._total_active_connections > 0:
            self._total_active_connections -= 1

    def check_message_rate(self, client_id: str) -> bool:
        """Verhindert WebSocket-Message-Flooding (Spamming)."""
        now = time.monotonic()
        history = self._client_message_history[client_id]
        cutoff = now - 1.0  # 1-Sekunden-Fenster

        while history and history[0] < cutoff:
            history.popleft()

        if len(history) >= self.max_messages_per_second:
            return False  # Rate limit überschritten

        history.append(now)
        return True

    def validate_message(self, message: str | bytes) -> bool:
        """Prüft die Payload-Größe einer eingehenden WebSocket-Nachricht."""
        size = len(message.encode("utf-8") if isinstance(message, str) else message)
        return size <= self.max_message_size


# Singleton-Instanz für WebSocket Security
ws_security_guard = WebSocketSecurityGuard()
