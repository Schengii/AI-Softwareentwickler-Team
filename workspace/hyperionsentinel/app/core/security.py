import hashlib
from collections.abc import Callable

from fastapi import HTTPException, Security, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Mock DB für API-Keys (in Produktion aus der echten DB laden)
API_KEY_DB = {
    hashlib.sha256(b"admin-secret-key").hexdigest(): "admin",
    hashlib.sha256(b"user-secret-key").hexdigest(): "user",
}

def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API Key")
    
    # CPU-bound Hashing in Threadpool auslagern, um Event-Loop nicht zu blockieren
    hashed_key = await run_in_threadpool(_hash_key, api_key)
    role = API_KEY_DB.get(hashed_key)
    
    if not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
    return role

def require_role(required_role: str) -> Callable:
    async def role_checker(role: str = Security(verify_api_key)) -> str:
        if role != required_role and role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return role
    return role_checker
