"""HMAC-SHA256 Signaturprüfung für eingehende Webhook-Payloads.

Verifiziert, dass eine über den `X-Signature`- bzw. `X-Hub-Signature-256`-Header
mitgesendete Signatur tatsächlich mit dem konfigurierten Secret der jeweiligen
Webhook-Quelle erzeugt wurde (Schutz gegen gefälschte/manipulierte Webhooks).
"""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Prüft eine HMAC-SHA256-Signatur timing-sicher gegen die erwartete Signatur.

    Args:
        payload: Der rohe Request-Body (als Bytes), über den die Signatur berechnet wurde.
        signature: Die vom Client mitgesendete Signatur, wahlweise mit oder ohne
            "sha256="-Präfix (GitHub/Shopify-Standard) als Hex-String.
        secret: Das für die Webhook-Quelle konfigurierte HMAC-Secret.

    Returns:
        True, wenn die Signatur gültig ist, sonst False. Leere/fehlende Werte
        werden immer als ungültig gewertet, statt eine Exception zu werfen.
    """
    if not signature or not secret:
        return False

    # GitHub/Shopify hängen der Signatur ein "sha256="-Präfix voran - für den Vergleich
    # muss nur der eigentliche Hex-Digest verwendet werden.
    if signature.startswith("sha256="):
        signature = signature[len("sha256="):]

    expected_signature = hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()

    # compare_digest statt "==", um Timing-Angriffe auf die Signaturprüfung zu verhindern.
    return hmac.compare_digest(expected_signature, signature)
