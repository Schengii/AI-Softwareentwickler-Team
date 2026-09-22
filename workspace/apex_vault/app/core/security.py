import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

api_key_header = APIKeyHeader(name="X-Vault-Token", auto_error=False)

def get_encryption_key(master_key: str) -> bytes:
    salt = b"apex_vault_salt"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
    return key

fernet = Fernet(get_encryption_key(settings.MASTER_KEY))

def encrypt_value(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()

def decrypt_value(encrypted_value: str) -> str:
    return fernet.decrypt(encrypted_value.encode()).decode()

async def get_current_user(request: Request, api_key: str = Security(api_key_header)):
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid token"
        )
    if api_key != settings.MASTER_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    return api_key
