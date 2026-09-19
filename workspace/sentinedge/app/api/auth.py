import secrets

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_api_key
from app.models.all import ApiKey
from app.schemas.all import ApiKeyCreate, ApiKeyCreateResponse
from app.services.audit import log_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/keys", response_model=ApiKeyCreateResponse)
async def create_api_key(
    key_in: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.future import select
    result = await db.execute(select(ApiKey).limit(1))
    first_key = result.scalar_one_or_none()

    if first_key:
        pass

    raw_secret = secrets.token_urlsafe(32)
    hashed_secret = await hash_api_key(raw_secret)

    new_key = ApiKey(
        name=key_in.name,
        key_hash=hashed_secret,
        scopes=key_in.scopes
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    full_raw_key = f"{new_key.id}.{raw_secret}"

    await log_audit(db, new_key.id, "create_api_key", f"key_id:{new_key.id}")

    return ApiKeyCreateResponse(
        id=new_key.id,
        name=new_key.name,
        scopes=new_key.scopes,
        is_active=new_key.is_active,
        created_at=new_key.created_at,
        raw_key=full_raw_key
    )
