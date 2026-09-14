
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.repositories.base import BaseRepository


class TenantRepository(BaseRepository[Tenant]):
    def __init__(self):
        super().__init__(Tenant)

    async def get_by_name(self, db: AsyncSession, name: str) -> Tenant | None:
        result = await db.execute(select(Tenant).where(Tenant.name == name))
        return result.scalars().first()

tenant_repo = TenantRepository()
