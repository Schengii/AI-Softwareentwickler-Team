import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic_settings import BaseSettings, SettingsConfigDict


class CryptoSettings(BaseSettings):
    # 32 bytes base64 encoded or hex string in production. Using a static 32 byte key for dev.
    ENCRYPTION_KEY: bytes = b"12345678901234567890123456789012"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = CryptoSettings()
aesgcm = AESGCM(settings.ENCRYPTION_KEY)

def encrypt_payload(data: bytes) -> bytes:
    """
    Encrypts data using AES-256-GCM.
    Returns: nonce (12 bytes) + ciphertext + tag (16 bytes)
    """
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext

def decrypt_payload(encrypted_data: bytes) -> bytes:
    """
    Decrypts data using AES-256-GCM.
    Expects: nonce (12 bytes) + ciphertext + tag (16 bytes)
    """
    if len(encrypted_data) < 28:
        raise ValueError("Invalid encrypted payload length")
    
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None)
