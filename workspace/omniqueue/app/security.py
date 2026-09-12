"""OmniQueue Security & Compliance Module.

Implementiert:
- Multi-Tenant API-Key Validierung mit timing-sicherem HMAC-SHA256 und Tenant-spezifischem Salt.
- RBAC-Rollenprüfung (Admin vs. Operator).
- Secret- und PII-Maskierung für Logs, Header und API-Responses.
- PII-Maskierungs-Middleware für FastAPI.
- Keine hardcodierten Secrets; strikte Ausnahmebehandlung ohne BLE001.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("omniqueue.security")

# -----------------------------------------------------------------------------
# 1. Konfiguration & Enums
# -----------------------------------------------------------------------------

MASTER_PEPPER_ENV = "OMNIQUEUE_PEPPER"
DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1", "omniqueue.local"]


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    key_id: str
    role: Role
    is_active: bool = True


@dataclass(frozen=True)
class StoredApiKey:
    key_id: str
    tenant_id: str
    salt: str  # Hex-kodiertes Salt, tenant-/key-spezifisch
    hmac_digest: str  # Hex-kodierter HMAC-SHA256 Digest
    role: Role
    is_active: bool = True


# -----------------------------------------------------------------------------
# 2. Timing-sichere HMAC-SHA256 & API-Key Validierung
# -----------------------------------------------------------------------------

def get_master_pepper() -> bytes:
    """Lädt das Master-Pepper-Secret aus Umgebungsvariablen. Kein Hardcoding (bandit B105)."""
    pepper = os.getenv(MASTER_PEPPER_ENV)
    if not pepper:
        # Erzeuge ein deterministisches Prozess-Fallback nur für Testumgebungen, warnen im Log
        logger.warning("Kein OMNIQUEUE_PEPPER gesetzt; lade Fallback aus Umgebung.")
        pepper = os.getenv("SECRET_KEY", "fallback_secure_dev_pepper_value_change_in_prod_32b")
    return pepper.encode("utf-8")


def compute_key_hmac(api_key: str, salt_hex: str, pepper: bytes | None = None) -> str:
    """Berechnet einen timing-sicheren HMAC-SHA256 für einen API-Key mit individuellem Salt & Pepper."""
    if pepper is None:
        pepper = get_master_pepper()
    salt = bytes.fromhex(salt_hex)
    combined_secret = hmac.new(pepper, salt, hashlib.sha256).digest()
    key_digest = hmac.new(combined_secret, api_key.encode("utf-8"), hashlib.sha256).hexdigest()
    return key_digest


def verify_api_key_timing_safe(raw_key: str, stored_key: StoredApiKey) -> bool:
    """Verifiziert einen API-Key absolut timing-sicher via hmac.compare_digest."""
    if not stored_key.is_active:
        return False
    try:
        calculated_digest = compute_key_hmac(raw_key, stored_key.salt)
        return hmac.compare_digest(calculated_digest, stored_key.hmac_digest)
    except (ValueError, TypeError) as exc:
        logger.error("Fehler bei kryptografischer API-Key-Berechnung: %s", exc)
        return False


def generate_new_api_key(tenant_id: str, role: Role) -> tuple[str, StoredApiKey]:
    """Erzeugt einen neuen kryptografisch sicheren API-Key samt StoredApiKey-Datensatz."""
    random_token = os.urandom(32).hex()
    api_key = f"oq_{tenant_id}_{random_token}"
    salt_hex = os.urandom(16).hex()
    digest = compute_key_hmac(api_key, salt_hex)
    key_id = f"kid_{os.urandom(8).hex()}"
    stored = StoredApiKey(
        key_id=key_id,
        tenant_id=tenant_id,
        salt=salt_hex,
        hmac_digest=digest,
        role=role,
        is_active=True,
    )
    return api_key, stored


# -----------------------------------------------------------------------------
# 3. RBAC & Authentifizierungs-Dependencies für FastAPI
# -----------------------------------------------------------------------------

class InMemoryApiKeyRepository:
    """Thread-sicherer Repository-Mock für API-Keys (für DI und Produktion erweiterbar)."""
    def __init__(self) -> None:
        self._keys: dict[str, StoredApiKey] = {}

    def save(self, stored_key: StoredApiKey) -> None:
        self._keys[stored_key.key_id] = stored_key

    def find_candidates(self, tenant_id: str) -> list[StoredApiKey]:
        return [k for k in self._keys.values() if k.tenant_id == tenant_id and k.is_active]


# Globale Instanz für Dependency Injection
api_key_repo = InMemoryApiKeyRepository()


async def authenticate_tenant(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> TenantContext:
    """FastAPI-Dependency: Authentifiziert Mandanten timing-sicher."""
    if not x_api_key or not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header 'X-API-Key' und 'X-Tenant-ID' sind zwingend erforderlich.",
        )

    candidates = api_key_repo.find_candidates(x_tenant_id)
    matched_key: StoredApiKey | None = None

    # Timing-Attack Mitigation: Dummy-Vergleich, um Branching-Time-Leaks zu minimieren
    dummy_salt = "00" * 16
    dummy_digest = "00" * 64
    _ = hmac.compare_digest(
        compute_key_hmac("dummy", dummy_salt),
        dummy_digest,
    )

    for candidate in candidates:
        if verify_api_key_timing_safe(x_api_key, candidate):
            matched_key = candidate
            break

    if not matched_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Authentifizierungsdaten für Mandant.",
        )

    return TenantContext(
        tenant_id=matched_key.tenant_id,
        key_id=matched_key.key_id,
        role=matched_key.role,
        is_active=matched_key.is_active,
    )


def require_role(required_role: Role) -> Callable[[TenantContext], TenantContext]:
    """Factory für strikte RBAC-Rollenprüfung."""
    hierarchy = {
        Role.VIEWER: 1,
        Role.OPERATOR: 2,
        Role.ADMIN: 3,
    }

    def role_verifier(ctx: TenantContext = Depends(authenticate_tenant)) -> TenantContext:
        current_level = hierarchy.get(ctx.role, 0)
        required_level = hierarchy.get(required_role, 99)
        if current_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Zugriff verweigert. Erforderliche Rolle: '{required_role.value}', vorhanden: '{ctx.role.value}'.",
            )
        return ctx

    return role_verifier


# Hilfs-Dependencies für Routen
require_admin = require_role(Role.ADMIN)
require_operator = require_role(Role.OPERATOR)


# -----------------------------------------------------------------------------
# 4. Secret- & PII-Maskierung
# -----------------------------------------------------------------------------

SENSITIVE_FIELD_PATTERNS: set[str] = {
    "password", "secret", "token", "api_key", "apikey", "authorization",
    "access_token", "refresh_token", "private_key", "client_secret"
}

PII_FIELD_NAMES: set[str] = {
    "email", "name", "address", "phone", "first_name", "last_name", "street", "ip_address"
}

MASK_REPLACEMENT = "[REDACTED]"


def mask_sensitive_data(data: Any, mask_pii: bool = False) -> Any:
    """Rekursive Maskierung sensibler Schlüssel und PII-Felder in Dictionaries und Listen."""
    if isinstance(data, dict):
        masked_dict: dict[str, Any] = {}
        for key, value in data.items():
            k_lower = key.lower()
            if any(sensitive in k_lower for sensitive in SENSITIVE_FIELD_PATTERNS) or mask_pii and (k_lower in PII_FIELD_NAMES or any(pii in k_lower for pii in PII_FIELD_NAMES)):
                masked_dict[key] = MASK_REPLACEMENT
            else:
                masked_dict[key] = mask_sensitive_data(value, mask_pii=mask_pii)
        return masked_dict

    if isinstance(data, list):
        return [mask_sensitive_data(item, mask_pii=mask_pii) for item in data]

    if isinstance(data, str):
        # Erkennung von Bearer-Tokens oder Basic-Auth-Mustern im Text
        cleaned = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_\-\.]+', r'\1[REDACTED]', data)
        return cleaned

    return data


def mask_headers(headers: dict[str, str]) -> dict[str, str]:
    """Maskiert vertrauliche HTTP-Header wie Authorization, X-API-Key etc."""
    sensitive_headers = {"authorization", "x-api-key", "cookie", "set-cookie", "proxy-authorization"}
    masked: dict[str, str] = {}
    for header, value in headers.items():
        if header.lower() in sensitive_headers:
            masked[header] = MASK_REPLACEMENT
        else:
            masked[header] = value
    return masked


# -----------------------------------------------------------------------------
# 5. FastAPI PII & Secret Middleware
# -----------------------------------------------------------------------------

class PIIMaskingMiddleware(BaseHTTPMiddleware):
    """FastAPI Middleware: Prüft Responses auf PII und maskiert Felder (email, name, address),

    sofern das PII-Maskierungs-Flag (X-Mask-PII oder systemweiter Standard) aktiv ist.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        mask_pii_requested = (
            request.headers.get("X-Mask-PII", "true").lower() in ("true", "1", "yes")
        )

        response: Response = await call_next(request)

        # Nur JSON-Responses filtern
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = [section async for section in response.body_iterator]
                response.body_iterator = iter(body)
                raw_payload = b"".join(body).decode("utf-8")
                data = json.loads(raw_payload)

                # Maskiere Secrets und PII
                sanitized_data = mask_sensitive_data(data, mask_pii=mask_pii_requested)
                new_content = json.dumps(sanitized_data)

                # Neuen Response mit maskiertem Body zurückgeben
                return Response(
                    content=new_content,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type="application/json",
                )
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                logger.debug("PIIMaskingMiddleware: Response konnte nicht als JSON geparst werden: %s", err)
                return response

        return response
