import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def mask_pii(data: str) -> str:
    """Masks PII data for audit logs."""
    if not data or len(data) < 4:
        return "***"
    return f"{data[:2]}***{data[-2:]}"

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        tenant_id: str = payload.get("tenant_id")
        if user_id is None or role is None or tenant_id is None:
            raise credentials_exception
        return {"user_id": user_id, "role": role, "tenant_id": tenant_id}
    except jwt.PyJWTError:
        raise credentials_exception

class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: dict[str, Any] = Depends(get_current_user)):
        if user.get("role") not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted"
            )
        return user

# Pre-defined role dependencies
require_admin = RoleChecker(["Admin"])
require_developer = RoleChecker(["Admin", "Developer"])
require_viewer = RoleChecker(["Admin", "Developer", "Viewer", "Auditor"])

def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
    """
    Validates HMAC API Key.
    In a real scenario, the salt/secret would be fetched from the DB based on the key ID.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key"
        )
    
    # Example: api_key format "key_id.hmac_signature"
    try:
        key_id, signature = api_key.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key format")
    
    # TODO: Fetch stored_secret for key_id from database
    # For now, we simulate it with a dummy secret
    stored_secret = b"dummy_secret_from_db" 
    
    expected_signature = hmac.new(
        stored_secret,
        key_id.encode(),
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    return True
