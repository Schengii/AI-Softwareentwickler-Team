import pytest
from app.core.encryption import encrypt, decrypt

def test_encryption_decryption_cycle():
    """Testet, ob verschlüsselte Daten korrekt wieder entschlüsselt werden."""
    original_text = "super-secret-data"
    encrypted = encrypt(original_text)
    decrypted = decrypt(encrypted)
    
    assert decrypted == original_text
    assert encrypted != original_text

def test_encryption_is_deterministic_or_random():
    """Prüft, ob Verschlüsselung bei gleichem Input unterschiedliche Ergebnisse liefert (IV)."""
    text = "secret"
    enc1 = encrypt(text)
    enc2 = encrypt(text)
    
    # Sollte bei sicherem AES-GCM/CBC mit IV unterschiedlich sein
    assert enc1 != enc2
