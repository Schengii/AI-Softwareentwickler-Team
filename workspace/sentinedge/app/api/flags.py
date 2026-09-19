from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.security import RequireScope
from app.models.all import ApiKey, FeatureFlag
from app.schemas.all import FeatureFlagCreate, FeatureFlagResponse
from app.services.audit import log_audit

router = APIRouter(prefix="/api/flags", tags=["flags"])

@router.post("", response_model=FeatureFlagResponse)
async def create_or_update_flag(
    flag_in: FeatureFlagCreate,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(RequireScope("flags:write"))
):
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == flag_in.key))
    flag = result.scalar_one_or_none()

    if flag:
        flag.is_enabled = flag_in.is_enabled
        flag.rollout_percentage = flag_in.rollout_percentage
        action = "update_flag"
    else:
        flag = FeatureFlag(
            key=flag_in.key,
            is_enabled=flag_in.is_enabled,
            rollout_percentage=flag_in.rollout_percentage
        )
        db.add(flag)
        action = "create_flag"

    await db.commit()
    await db.refresh(flag)

    await log_audit(db, api_key.id, action, flag.key, {"is_enabled": flag.is_enabled, "rollout": flag.rollout_percentage})
    return flag

@router.get("/{key}", response_model=FeatureFlagResponse)
async def get_flag(
    key: str,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(RequireScope("flags:read"))
):
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))
    flag = result.scalar_one_or_none()

    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found")

    await log_audit(db, api_key.id, "read_flag", key)
    return flag
