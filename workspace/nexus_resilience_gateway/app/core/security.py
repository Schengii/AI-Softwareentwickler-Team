"""
Nexus Resilience Gateway - Security & HMAC Signature Verifier
Implementiert HMAC-SHA256 Signaturprüfung und Replay-Schutz (Timestamp/Nonce).
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request, status


class SecurityVerificationError(HTTPException):
    """Spezifische Gateway-Security Exception."""
    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(
            status_code=status_code,
            detail={"error": error_code, "message": message, "timestamp": int(time.time())}
        )


class NonceTracker:
    """
    Sliding-Window Nonce-Speicher zur Vermeidung von Replay-Angriffen.
    Arbeitet mit time.monotonic() für gleichmäßige TTL-Messung ohne Clock-Jumps.
    """
    def __init__(self, ttl_seconds: float = 600.0):
        self.ttl_seconds = ttl_seconds
        # Mapping: (tenant_id, nonce) -> expire_monotonic
        self._nonces: dict[tuple[str, str], float] = {}

    def check_and_store(self, tenant_id: str, nonce: str) -> bool:
        """
        Prüft atomar, ob eine Nonce bereits verwendet wurde.
        Gibt True zurück, wenn die Nonce neu ist und registriert wurde.
        Gibt False zurück, wenn es sich um einen Replay-Versuch handelt.
        """
        now = time.monotonic()
        self._purge_expired(now)

        key = (tenant_id, nonce)
        if key in self._nonces:
            return False

        self._nonces[key] = now + self.ttl_seconds
        return True

    def _purge_expired(self, now: float) -> None:
        """Entfernt abgelaufene Nonces aus dem Speicher."""
        expired_keys = [k for k, exp in self._nonces.items() if exp <= now]
        for k in expired_keys:
            self._nonces.pop(k, None)


# Singleton-Tracker für In-Memory-Validierung
_nonce_tracker = NonceTracker(ttl_seconds=600.0)


def calculate_hmac_sha256(secret_key: str, timestamp: int, nonce: str, raw_body: bytes) -> str:
    """Berechnet die kanonische HMAC-SHA256 Hex-Signatur."""
    canonical_payload = f"{timestamp}.{nonce}.".encode() + raw_body
    return hmac.new(
        key=secret_key.encode("utf-8"),
        msg=canonical_payload,
        digestmod=hashlib.sha256
    ).hexdigest()


async def verify_hmac_and_replay_protection(
    request: Request,
    secret_key: str,
    max_drift_seconds: int = 300,
    nonce_tracker: NonceTracker | None = None
) -> bytes:
    """
    Validiert Ingress-Requests gegen HMAC-Fälschungen und Replay-Angriffe.
    
    Header-Voraussetzungen:
      - X-Signature: sha256=<hex_digest>
      - X-Timestamp: <unix_seconds>
      - X-Nonce: <eindeutiger_string>
      - X-Tenant-Key: <mandanten_schlüssel>
    """
    tracker = nonce_tracker or _nonce_tracker
    
    # 1. Header-Extraktion
    signature_header = request.headers.get("X-Signature")
    timestamp_header = request.headers.get("X-Timestamp")
    nonce = request.headers.get("X-Nonce")
    tenant_key = request.headers.get("X-Tenant-Key", "anonymous")

    if not signature_header or not timestamp_header or not nonce:
        raise SecurityVerificationError(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="MISSING_SECURITY_HEADERS",
            message="Header 'X-Signature', 'X-Timestamp' und 'X-Nonce' sind erforderlich."
        )

    # 2. Timestamp Drift-Check (Replay Prevention Stufe 1)
    try:
        req_timestamp = int(timestamp_header)
    except ValueError:
        raise SecurityVerificationError(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_TIMESTAMP_FORMAT",
            message="'X-Timestamp' muss ein ganzzahliger Unix-Timestamp in Sekunden sein."
        )

    current_unix_time = int(time.time())
    if abs(current_unix_time - req_timestamp) > max_drift_seconds:
        raise SecurityVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="TIMESTAMP_OUT_OF_BOUNDS",
            message=f"Timestamp-Drift überschreitet das Toleranzfenster von {max_drift_seconds}s."
        )

    # 3. Nonce Check (Replay Prevention Stufe 2)
    if len(nonce) < 16:
        raise SecurityVerificationError(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INSUFFICIENT_NONCE_ENTROPY",
            message="'X-Nonce' muss eine Mindestlänge von 16 Zeichen aufweisen."
        )

    if not tracker.check_and_store(tenant_key, nonce):
        raise SecurityVerificationError(
            status_code=status.HTTP_409_CONFLICT,
            error_code="REPLAY_ATTACK_DETECTED",
            message="Replay erkannt: Nonce wurde innerhalb des Gültigkeitsfensters bereits verwendet."
        )

    # 4. Raw Body für Signaturberechnung lesen
    raw_body = await request.body()

    # 5. Signaturformat prüfen und matchen
    expected_prefix = "sha256="
    provided_signature = signature_header
    provided_signature = provided_signature.removeprefix(expected_prefix)

    computed_signature = calculate_hmac_sha256(
        secret_key=secret_key,
        timestamp=req_timestamp,
        nonce=nonce,
        raw_body=raw_body
    )

    if not hmac.compare_digest(provided_signature, computed_signature):
        raise SecurityVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="INVALID_SIGNATURE",
            message="HMAC-SHA256 Signatur stimmt nicht mit dem berechneten Digest überein."
        )

    return raw_body


class SecurityManager:
    """
    Zentraler Sicherheitsmanager für Gateway-Authentifizierung,
    Signaturvalidierung und Replay-Schutz gemäß Interface-Vertrag.
    """

    def __init__(
        self,
        nonce_tracker: NonceTracker | None = None,
        max_drift_seconds: int = 300,
    ) -> None:
        self.nonce_tracker = nonce_tracker or _nonce_tracker
        self.max_drift_seconds = max_drift_seconds

    def calculate_signature(
        self, secret_key: str, timestamp: int, nonce: str, raw_body: bytes
    ) -> str:
        """Berechnet die kanonische HMAC-SHA256-Signatur."""
        return calculate_hmac_sha256(secret_key, timestamp, nonce, raw_body)

    async def verify_request(self, request: Request, secret_key: str) -> bytes:
        """Verifiziert eingehende Requests auf HMAC-Signatur und Replay-Sicherheit."""
        return await verify_hmac_and_replay_protection(
            request=request,
            secret_key=secret_key,
            max_drift_seconds=self.max_drift_seconds,
            nonce_tracker=self.nonce_tracker,
        )

    def check_nonce(self, tenant_id: str, nonce: str) -> bool:
        """Überprüft und registriert eine Nonce zur Vermeidung von Replays."""
        return self.nonce_tracker.check_and_store(tenant_id, nonce)


# Singleton-Instanz gemäß Interface-Vertrag (app/core/security.py: security_manager)
security_manager = SecurityManager()
