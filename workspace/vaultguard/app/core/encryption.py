import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EncryptionService:
    def __init__(self, master_key: str):
        # Ableitung eines 256-Bit Keys aus dem Master-Key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'vaultguard_salt', # In Produktion durch ein sicheres, gespeichertes Salt ersetzen
            iterations=100000,
        )
        self.key = kdf.derive(master_key.encode())
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, data: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, data.encode(), None)
        return base64.b64encode(nonce + ciphertext).decode('utf-8')

    def decrypt(self, encrypted_data: str) -> str:
        raw_data = base64.b64decode(encrypted_data)
        nonce, ciphertext = raw_data[:12], raw_data[12:]
        return self.aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')
