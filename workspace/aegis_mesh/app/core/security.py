"""Security-Modul für HMAC-Validierung, Replay-Schutz und PII-Maskierung."""

import hashlib
import hmac
import logging
import re
import time

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# In-Memory Cache für Nonces (Replay-Schutz)
_nonce_cache: dict[str, float] = {}


def _cleanup_nonce_cache(max_drift: int) -> None:
    """Entfernt abgelaufene Nonces aus dem Cache, um Speicherlecks zu vermeiden."""
    now = time.time()
    expired = [
        nonce for nonce, timestamp in _nonce_cache.items() if now - timestamp > max_drift
    ]
    for nonce in expired:
        del _nonce_cache[nonce]


class PIIMasker:
    """Hilfsklasse zur Maskierung von PII (Personally Identifiable Information) in Logs."""

    PII_FIELDS = {"email", "name", "address", "phone", "password", "credit_card"}

    @staticmethod
    def mask_ip(ip: str | None) -> str:
        """Maskiert eine IPv4 oder IPv6 Adresse."""
        if not ip:
            return "unknown"
        if ":" in ip:  # IPv6
            parts = ip.split(":")
            return ":".join(parts[:4]) + ":***"
        # IPv4
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.***.***"
        return "***"

    @staticmethod
    def mask_payload(payload: dict) -> dict:
        """Maskiert sensitive Felder in einem Dictionary (z.B. JSON Payload)."""
        masked = {}
        for k, v in payload.items():
            if k.lower() in PIIMasker.PII_FIELDS:
                masked[k] = "***"
            elif isinstance(v, dict):
                masked[k] = PIIMasker.mask_payload(v)
            elif isinstance(v, list):
                masked[k] = [
                    PIIMasker.mask_payload(i) if isinstance(i, dict) else "***"
                    if k.lower() in PIIMasker.PII_FIELDS else i
                    for i in v
                ]
            else:
                masked[k] = v
        return masked

    @staticmethod
    def mask_log_string(text: str) -> str:
        """Maskiert E-Mail-Adressen in einfachen Strings."""
        return re.sub(
            r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "***@***.***", text
        )


class SecurityValidator:
    """
    FastAPI Dependency zur Validierung von HMAC-Signaturen und 
    zum Schutz vor Replay-Attacken (Zero-Trust).
    """

    def __init__(self, settings: Settings = Depends(get_settings)):
        self.settings = settings

    async def __call__(self, request: Request) -> bool:
        """
        Validiert den Request.
        Erwartet Header: X-Signature, X-Timestamp, X-Nonce.
        """
        signature = request.headers.get("X-Signature")
        timestamp_str = request.headers.get("X-Timestamp")
        nonce = request.headers.get("X-Nonce")

        client_ip = request.client.host if request.client else "unknown"
        masked_ip = PIIMasker.mask_ip(client_ip)

        if not signature or not timestamp_str or not nonce:
            logger.warning(f"Fehlende Security-Header von IP {masked_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing security headers",
            )

        try:
            timestamp = float(timestamp_str)
        except ValueError:
            logger.warning(f"Ungültiges Timestamp-Format von IP {masked_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid timestamp format",
            )

        now = time.time()
        if abs(now - timestamp) > self.settings.MAX_TIMESTAMP_DRIFT_SECONDS:
            logger.warning(f"Timestamp-Drift überschritten für IP {masked_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Timestamp out of acceptable range",
            )

        _cleanup_nonce_cache(self.settings.MAX_TIMESTAMP_DRIFT_SECONDS)

        if nonce in _nonce_cache:
            logger.warning(f"Replay-Attacke erkannt (Nonce wiederverwendet) von IP {masked_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Replay attack detected",
            )

        # Body lesen für Signatur (Request Body kann mehrfach gelesen werden, 
        # wenn wir ihn nicht konsumieren, aber in FastAPI ist das sicher, 
        # wenn wir request.body() nutzen)
        body = await request.body()

        # Signatur berechnen: HMAC-SHA256(timestamp + nonce + body)
        message = timestamp_str.encode() + nonce.encode() + body
        expected_signature = hmac.new(
            self.settings.HMAC_SECRET.encode(), message, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            logger.warning(f"Ungültige HMAC-Signatur von IP {masked_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature"
            )

        # Nonce speichern
        _nonce_cache[nonce] = timestamp

        return True
