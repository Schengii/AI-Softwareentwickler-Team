
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feature_flag import FeatureFlag
from app.repositories.base import BaseRepository


class FeatureFlagRepository(BaseRepository[FeatureFlag]):
    def __init__(self):
        super().__init__(FeatureFlag)

    async def get_by_key(self, db: AsyncSession, tenant_id: str, key: str) -> FeatureFlag | None:
        result = await db.execute(
            select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id, FeatureFlag.key == key)
        )
        return result.scalars().first()

    async def get_all_for_tenant(self, db: AsyncSession, tenant_id: str) -> list[FeatureFlag]:
        result = await db.execute(select(FeatureFlag).where(FeatureFlag.tenant_id == tenant_id))
        return list(result.scalars().all())

feature_flag_repo = FeatureFlagRepository()
