import os

import pytest

from app.core.crypto import CryptoService


def test_crypto_service_encryption_decryption():
    master_key = os.urandom(32).hex()
    service = CryptoService(master_key)
    
    plaintext = "my_super_secret_value"
    encrypted = service.encrypt(plaintext)
    
    assert encrypted != plaintext.encode('utf-8')
    assert len(encrypted) > len(plaintext)
    
    decrypted = service.decrypt(encrypted)
    assert decrypted == plaintext

def test_crypto_service_invalid_key_length():
    with pytest.raises(ValueError):
        CryptoService(os.urandom(16).hex())

def test_crypto_service_tampered_ciphertext():
    master_key = os.urandom(32).hex()
    service = CryptoService(master_key)
    
    encrypted = service.encrypt("test")
    tampered = bytearray(encrypted)
    tampered[-1] ^= 1 # Flip a bit in the ciphertext/tag
    
    from cryptography.exceptions import InvalidTag
    with pytest.raises(InvalidTag):
        service.decrypt(bytes(tampered))
