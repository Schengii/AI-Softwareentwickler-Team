from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def timing_safe_hmac_verify(provided_secret: str, expected_secret: str) -> bool:
    if not provided_secret or not expected_secret:
        return False
    return hmac.compare_digest(provided_secret.encode("utf-8"), expected_secret.encode("utf-8"))


def hash_token(token: str) -> str:
    """Erzeugt einen SHA-256-Hash des übergebenen Tokens."""
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> bool:
    """Validiert den übergebenen API-Key im X-API-Key Header."""
    settings = get_settings()
    configured_key = getattr(settings, "API_KEY", None) or getattr(settings, "api_key", None)
    
    # Falls in Settings kein API-Key hinterlegt ist oder DEV-Modus aktiv ist
    if not configured_key:
        return True

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key in X-API-Key header",
        )

    if not timing_safe_hmac_verify(api_key, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    return True
