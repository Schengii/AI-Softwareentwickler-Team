from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.vault_item import SecretStatus
from app.services.vault_service import (
    SecretCreate,
    create_secret,
    get_secret,
    revoke_secret,
)


class SecretResponse(BaseModel):
    name: str
    status: SecretStatus
    ttl_seconds: int | None = None
    metadata: dict | None = Field(default=None, alias="metadata_json")
    created_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}

class SecretValueResponse(BaseModel):
    name: str
    value: str

router = APIRouter(prefix="/secrets", tags=["secrets"])

@router.post("", response_model=SecretResponse)
async def create_new_secret(
    request: Request,
    secret_in: SecretCreate,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    actor_ip = request.client.host if request.client else "unknown"
    return await create_secret(db, secret_in, actor_ip)

@router.get("/{name}", response_model=SecretValueResponse)
async def read_secret(
    request: Request,
    name: str,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    actor_ip = request.client.host if request.client else "unknown"
    value = await get_secret(db, name, actor_ip)
    return SecretValueResponse(name=name, value=value)

@router.post("/{name}/revoke", response_model=SecretResponse)
async def revoke_existing_secret(
    request: Request,
    name: str,
    db: AsyncSession = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    actor_ip = request.client.host if request.client else "unknown"
    return await revoke_secret(db, name, actor_ip)
