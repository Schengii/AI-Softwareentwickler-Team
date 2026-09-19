import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class CryptoService:
    def __init__(self, master_key_hex: str):
        # master_key_hex should be 64 chars (32 bytes)
        self.key = bytes.fromhex(master_key_hex)
        if len(self.key) != 32:
            raise ValueError("Master key must be exactly 32 bytes for AES-256")
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, plaintext: str) -> bytes:
        nonce = os.urandom(12) # 96-bit nonce for GCM
        ciphertext = self.aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        return nonce + ciphertext

    def decrypt(self, encrypted_data: bytes) -> str:
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        from cryptography.exceptions import InvalidTag
        try:
            plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode('utf-8')
        except InvalidTag:
            raise ValueError("Integrity check failed")

crypto_service = CryptoService(get_settings().MASTER_KEY)
