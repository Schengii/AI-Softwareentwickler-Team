import secrets
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(api_key_header: str = Security(api_key_header)) -> str:
    if not api_key_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key missing"
        )
    if secrets.compare_digest(api_key_header, settings.API_KEY):
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate API Key"
    )
