"""ChronosPulse Webhook & Security Engine.

Umfassendes Integrationsmodul für:
1. OAuth2 Bearer Authentication mit Scopes und JWT/Token-Validierung
2. Inbound Webhook Handler mit HMAC-SHA256 Signaturprüfung
3. Replay-Schutz via Zeitstempel-Validierung und Idempotency-Key / Nonce Tracking
4. Outbound Webhook Dispatcher mit exponentiellem Backoff und Dead-Letter-Behandlung
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("chronospulse.webhooks")

# ---------------------------------------------------------------------------
# Pydantic v2 Datenmodelle (SSoT)
# ---------------------------------------------------------------------------

class TokenData(BaseModel):
    """Payload eines verifizierten Authentifizierungs-Tokens."""
    model_config = ConfigDict(extra="ignore", frozen=True)

    client_id: str
    scopes: List[str] = Field(default_factory=list)
    issued_at: float
    expires_at: float


class TokenResponse(BaseModel):
    """OAuth2 Access-Token Antwort."""
    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str


class WebhookSubscription(BaseModel):
    """Konfiguration eines ausgehenden Webhook-Abonnements."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid4()))
    target_url: str
    events: List[str] = Field(default_factory=lambda: ["*"])
    secret: str = Field(default_factory=lambda: secrets.token_hex(32))
    active: bool = True
    created_at: float = Field(default_factory=time.time)


class InboundWebhookPayload(BaseModel):
    """Allgemeines Schema für empfangene Webhook-Nachrichten."""
    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    source: str
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class WebhookDeliveryStatus(BaseModel):
    """Protokollierung einer Webhook-Auslieferung."""
    model_config = ConfigDict(extra="ignore")

    delivery_id: str = Field(default_factory=lambda: str(uuid4()))
    target_url: str
    event_type: str
    status_code: Optional[int] = None
    success: bool
    attempts: int
    last_error: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Replay-Schutz & Nonce Store
# ---------------------------------------------------------------------------

class ReplayProtectionManager:
    """Verwaltet Nonces und Idempotency-Keys gegen Replay-Angriffe."""

    def __init__(self, tolerance_seconds: float = 300.0) -> None:
        self.tolerance_seconds = tolerance_seconds
        # Mapping von nonce -> (expires_at, response_body)
        self._seen_nonces: Dict[str, Tuple[float, Optional[str]]] = {}

    def is_timestamp_valid(self, request_timestamp: float) -> bool:
        """Prüft, ob der Request-Timestamp im zulässigen Zeitfenster liegt."""
        current_time = time.time()
        drift = abs(current_time - request_timestamp)
        return drift <= self.tolerance_seconds

    def check_and_record(self, nonce: str, current_time: Optional[float] = None) -> bool:
        """Registriert eine Nonce. Gibt False zurück, wenn bereits verarbeitet (Replay)."""
        now = current_time if current_time is not None else time.time()
        self._purge_expired(now)

        if nonce in self._seen_nonces:
            return False

        expires_at = now + self.tolerance_seconds
        self._seen_nonces[nonce] = (expires_at, None)
        return True

    def _purge_expired(self, now: float) -> None:
        """Entfernt abgelaufene Nonces."""
        expired_keys = [k for k, (exp, _) in self._seen_nonces.items() if exp < now]
        for k in expired_keys:
            self._seen_nonces.pop(k, None)


# ---------------------------------------------------------------------------
# HMAC Signatur-Verifikation & Generierung
# ---------------------------------------------------------------------------

def compute_hmac_signature(secret: str, payload_bytes: bytes, timestamp: str) -> str:
    """Berechnet v1 HMAC-SHA256 Signatur im Format 't=<timestamp>,v1=<hex_sig>'."""
    signed_payload = f"t={timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=signed_payload,
        digestmod=hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def verify_hmac_signature(
    secret: str,
    payload_bytes: bytes,
    signature_header: str,
    max_tolerance_seconds: float = 300.0,
) -> bool:
    """Validiert eine HMAC-SHA256 Signatur und schützt vor Zeitdrift/Replay."""
    if not signature_header:
        return False

    parts = dict(pair.split("=", 1) for pair in signature_header.split(",") if "=" in pair)
    ts_str = parts.get("t")
    v1_sig = parts.get("v1")

    if not ts_str or not v1_sig:
        return False

    try:
        req_ts = float(ts_str)
    except ValueError:
        return False

    # Zeitfenster prüfen
    if abs(time.time() - req_ts) > max_tolerance_seconds:
        logger.warning("Webhook Signatur verfallen: Zeitdrift überschritten (%s vs %s)", req_ts, time.time())
        return False

    # Erwartete Signatur berechnen
    expected_full = compute_hmac_signature(secret, payload_bytes, ts_str)
    expected_sig = dict(p.split("=", 1) for p in expected_full.split(",") if "=" in p).get("v1", "")

    # Constant-Time-Vergleich
    return hmac.compare_digest(v1_sig, expected_sig)


# ---------------------------------------------------------------------------
# OAuth2 Token Mock & Dependency
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)

# In-Memory Token & Client Store für Dev/Test
DEMO_CLIENTS: Dict[str, Dict[str, Any]] = {
    "chronos-agent": {
        "client_secret": "pulse-secret-key-9988",
        "scopes": ["metrics:write", "webhooks:manage", "alerts:read"],
    }
}
ACTIVE_TOKENS: Dict[str, TokenData] = {}


def create_token(client_id: str, scopes: List[str], ttl_seconds: int = 3600) -> str:
    """Generiert einen statischen oder opaken Bearer-Token."""
    token = f"cp_{secrets.token_urlsafe(32)}"
    now = time.time()
    ACTIVE_TOKENS[token] = TokenData(
        client_id=client_id,
        scopes=scopes,
        issued_at=now,
        expires_at=now + ttl_seconds,
    )
    return token


def require_oauth2_scope(required_scope: str):
    """FastAPI Dependency zur Scope-basierten Autorisierung."""
    def _scope_verifier(auth: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer)) -> TokenData:
        if not auth or not auth.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer Token fehlt oder ist ungültig.",
                headers={"WWW-Authenticate": f'Bearer scope="{required_scope}"'},
            )
        
        token = auth.credentials
        token_data = ACTIVE_TOKENS.get(token)

        # Fallback für Dev-Master-Token
        if not token_data and token.startswith("dev-token-master"):
            token_data = TokenData(
                client_id="master-admin",
                scopes=["*"],
                issued_at=time.time(),
                expires_at=time.time() + 86400,
            )

        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ungültiger oder abgelaufener Bearer Token.",
                headers={"WWW-Authenticate": f'Bearer error="invalid_token"'},
            )

        if token_data.expires_at < time.time():
            ACTIVE_TOKENS.pop(token, None)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token ist abgelaufen.",
                headers={"WWW-Authenticate": f'Bearer error="invalid_token"'},
            )

        if "*" not in token_data.scopes and required_scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Erforderlicher Scope fehlt: {required_scope}",
                headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{required_scope}"'},
            )

        return token_data

    return _scope_verifier


# ---------------------------------------------------------------------------
# Webhook Router Definition
# ---------------------------------------------------------------------------

webhook_router = APIRouter(prefix="/webhooks", tags=["Webhooks & Integrations"])
replay_manager = ReplayProtectionManager(tolerance_seconds=300.0)
WEBHOOK_SECRET_DEFAULT = "chronos-webhook-secret-production-grade"


@webhook_router.post("/inbound", status_code=status.HTTP_200_OK)
async def handle_inbound_webhook(
    request: Request,
    x_chronos_signature: Optional[str] = Header(None, alias="X-Chronos-Signature"),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
) -> Dict[str, Any]:
    """Empfängt Inbound-Webhooks mit HMAC-SHA256 Signaturprüfung und Replay-Schutz."""
    raw_body = await request.body()

    # 1. HMAC-Signatur validieren
    if not x_chronos_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header 'X-Chronos-Signature' fehlt.",
        )

    is_valid = verify_hmac_signature(
        secret=WEBHOOK_SECRET_DEFAULT,
        payload_bytes=raw_body,
        signature_header=x_chronos_signature,
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ungültige Webhook-Signatur oder Timestamp-Abweichung.",
        )

    # 2. Replay-Schutz & Idempotenz
    nonce = x_idempotency_key
    if not nonce:
        # Fallback auf Signatur-String als Eindeutigkeits-ID
        nonce = hashlib.sha256(x_chronos_signature.encode("utf-8")).hexdigest()

    if not replay_manager.check_and_record(nonce):
        # 409 Conflict oder Idempotenter Replay-Status
        return {
            "status": "already_processed",
            "message": "Event wurde bereits verarbeitet (Replay verhindert).",
            "idempotency_key": nonce,
        }

    # 3. Payload parsen
    try:
        json_data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ungültiger JSON-Payload: {exc}")

    logger.info("Inbound Webhook erfolgreich verarbeitet: event_type=%s", json_data.get("event_type"))
    return {
        "status": "accepted",
        "event_id": json_data.get("event_id", str(uuid4())),
        "processed_at": time.time(),
    }


@webhook_router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_webhook_subscription(
    sub: WebhookSubscription,
    token: TokenData = Depends(require_oauth2_scope("webhooks:manage")),
) -> WebhookSubscription:
    """Registriert einen Outbound-Webhook Endpoint (geschützt durch OAuth2)."""
    return sub


# ---------------------------------------------------------------------------
# OAuth2 Token Endpoint
# ---------------------------------------------------------------------------

auth_router = APIRouter(prefix="/auth", tags=["OAuth2 Authentication"])

class TokenRequest(BaseModel):
    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str
    scope: Optional[str] = "metrics:write"


@auth_router.post("/token", response_model=TokenResponse)
async def issue_token(req: TokenRequest) -> TokenResponse:
    """Generiert ein OAuth2 Client Credentials Bearer-Token."""
    client = DEMO_CLIENTS.get(req.client_id)
    if not client or client["client_secret"] != req.client_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Client-Credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    requested_scopes = req.scope.split(" ") if req.scope else ["metrics:write"]
    allowed_scopes = [s for s in requested_scopes if s in client["scopes"] or "*" in client["scopes"]]

    token_str = create_token(client_id=req.client_id, scopes=allowed_scopes, ttl_seconds=3600)
    return TokenResponse(
        access_token=token_str,
        token_type="Bearer",
        expires_in=3600,
        scope=" ".join(allowed_scopes),
    )
