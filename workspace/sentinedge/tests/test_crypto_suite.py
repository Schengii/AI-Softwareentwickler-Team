import pytest

from app.core.crypto import CryptoService


@pytest.fixture
def crypto_service():
    # Master Key für Tests (32 Bytes hex)
    return CryptoService(master_key_hex="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

def test_crypto_service_encryption_decryption(crypto_service):
    secret = "my-super-secret-value"
    
    # Verschlüsseln
    encrypted_data = crypto_service.encrypt(secret)
    assert encrypted_data != secret
    
    # Entschlüsseln
    decrypted_data = crypto_service.decrypt(encrypted_data)
    assert decrypted_data == secret

def test_crypto_service_integrity_failure(crypto_service):
    secret = "my-super-secret-value"
    encrypted_data = crypto_service.encrypt(secret)
    
    # Manipulation der verschlüsselten Daten (AES-GCM Tag korrumpieren)
    corrupted_data = encrypted_data[:-1] + b"X"
    
    with pytest.raises(ValueError):
        crypto_service.decrypt(corrupted_data)
