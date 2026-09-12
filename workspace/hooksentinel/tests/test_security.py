"""
Test-Suite für Sicherheits- und Integritätsfunktionen von HookSentinel.
Behandelt HMAC-SHA256 Signaturprüfung und Idempotenz-Prüfungen.
"""
import hashlib
import hmac

from app.services.security import verify_hmac_signature


def generate_signature(secret: str, payload: bytes) -> str:
    """Hilfsfunktion zum Generieren einer gültigen HMAC-SHA256 Signatur im Hex-Format."""
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def test_hmac_valid_signature():
    """Gültige Signatur muss erfolgreich validiert werden."""
    secret = "super-secret-key-123"
    payload = b'{"event": "payment.succeeded", "amount": 100}'
    signature = generate_signature(secret, payload)

    # Teste direkten Hex-String
    assert verify_hmac_signature(payload, signature, secret) is True
    # Teste sha256= Präfix (GitHub/Shopify Standard)
    assert verify_hmac_signature(payload, f"sha256={signature}", secret) is True


def test_hmac_invalid_signature():
    """Ungültige Signatur muss abgewiesen werden."""
    secret = "super-secret-key-123"
    payload = b'{"event": "payment.succeeded", "amount": 100}'
    bad_signature = "0" * 64

    assert verify_hmac_signature(payload, bad_signature, secret) is False
    assert verify_hmac_signature(payload, f"sha256={bad_signature}", secret) is False


def test_hmac_tampered_payload():
    """Modifizierte Payload bei gleicher Signatur muss abgewiesen werden."""
    secret = "super-secret-key-123"
    original_payload = b'{"event": "payment.succeeded", "amount": 100}'
    tampered_payload = b'{"event": "payment.succeeded", "amount": 1000000}'
    signature = generate_signature(secret, original_payload)

    assert verify_hmac_signature(tampered_payload, signature, secret) is False


def test_hmac_empty_secret_or_signature():
    """Leere Secrets oder Signaturen müssen abgewiesen werden."""
    payload = b'{"data": "test"}'
    assert verify_hmac_signature(payload, "", "secret") is False
    assert verify_hmac_signature(payload, "some-sig", "") is False
