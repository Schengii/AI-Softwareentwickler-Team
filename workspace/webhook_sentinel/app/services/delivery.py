import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.webhook import Delivery

class DeliveryService:
    async def get_delivery(self, db: AsyncSession, delivery_id: uuid.UUID) -> Optional[Delivery]:
        result = await db.execute(select(Delivery).where(Delivery.id == delivery_id))
        return result.scalar_one_or_none()

    async def retry_delivery(self, db: AsyncSession, delivery_id: uuid.UUID) -> Optional[Delivery]:
        delivery = await self.get_delivery(db, delivery_id)
        if not delivery:
            return None
        # Logic for retrying delivery would go here
        return delivery

delivery_service = DeliveryService()
