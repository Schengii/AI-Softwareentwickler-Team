import pytest

from app.core.encryption import EncryptionService


@pytest.fixture
def encryption_service():
    return EncryptionService(master_key="test-secret-key")

def test_encryption_decryption_cycle(encryption_service):
    """Testet, ob verschlüsselte Daten korrekt wieder entschlüsselt werden."""
    original_text = "super-secret-data"
    encrypted = encryption_service.encrypt(original_text)
    decrypted = encryption_service.decrypt(encrypted)
    
    assert decrypted == original_text
    assert encrypted != original_text

def test_encryption_is_deterministic_or_random(encryption_service):
    """Prüft, ob Verschlüsselung bei gleichem Input unterschiedliche Ergebnisse liefert (IV)."""
    text = "secret"
    enc1 = encryption_service.encrypt(text)
    enc2 = encryption_service.encrypt(text)
    
    # Sollte bei sicherem AES-GCM mit IV unterschiedlich sein
    assert enc1 != enc2
