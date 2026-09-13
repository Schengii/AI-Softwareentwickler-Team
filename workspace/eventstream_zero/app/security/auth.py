import time

import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.security.audit import log_audit_event


class SecuritySettings(BaseSettings):
    SECRET_KEY: str = "dev-secret-key-change-in-production-1234567890"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = SecuritySettings()
security = HTTPBearer()

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = time.time() + (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise ValueError("Missing sub")
        return payload
    except jwt.ExpiredSignatureError:
        log_audit_event("ACCESS_DENIED", "unknown", "api", "authenticate", "FAILURE", {"reason": "token_expired"})
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        log_audit_event("ACCESS_DENIED", "unknown", "api", "authenticate", "FAILURE", {"reason": "invalid_token"})
        raise HTTPException(status_code=401, detail="Invalid credentials")

def require_role(required_role: str):
    def role_checker(user: dict = Depends(get_current_user)):
        roles = user.get("roles", [])
        if required_role not in roles and "admin" not in roles:
            log_audit_event("ACCESS_DENIED", user.get("sub"), "api", "check_role", "FAILURE", {"required": required_role})
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return role_checker
