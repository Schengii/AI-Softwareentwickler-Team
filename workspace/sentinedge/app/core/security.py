import anyio
import bcrypt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.models.all import ApiKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj2C.OQ.zE2m"

async def hash_api_key(api_key: str) -> str:
    def _hash():
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(api_key.encode('utf-8'), salt).decode('utf-8')
    return await anyio.to_thread.run_sync(_hash)

async def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    def _verify():
        try:
            return bcrypt.checkpw(plain_key.encode('utf-8'), hashed_key.encode('utf-8'))
        except ValueError:
            return False
    return await anyio.to_thread.run_sync(_verify)

async def get_current_api_key(
    api_key: str = Security(api_key_header),
    db: AsyncSession = Depends(get_db)
) -> ApiKey:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key"
        )
    
    try:
        key_id_str, secret = api_key.split(".", 1)
        key_id = int(key_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key format. Expected 'id.secret'"
        )

    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    db_key = result.scalar_one_or_none()

    if not db_key or not db_key.is_active:
        await verify_api_key(secret, DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API Key"
        )

    if not await verify_api_key(secret, db_key.key_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )

    return db_key

class RequireScope:
    def __init__(self, required_scope: str):
        self.required_scope = required_scope

    async def __call__(self, api_key: ApiKey = Depends(get_current_api_key)):
        scopes = [s.strip() for s in api_key.scopes.split(",") if s.strip()]
        if self.required_scope not in scopes and "admin" not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not enough permissions. Required scope: {self.required_scope}"
            )
        return api_key
