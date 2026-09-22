import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.webhook import Delivery
from app.schemas.webhook import DeliveryResponse
from app.services.dispatcher import dispatcher

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.get("", response_model=List[DeliveryResponse])
async def list_deliveries(
    subscription_id: Optional[uuid.UUID] = Query(None, description="Filter nach Subscription-ID"),
    event_id: Optional[str] = Query(None, description="Filter nach Event-ID"),
    status_code: Optional[int] = Query(None, description="Filter nach HTTP-Statuscode"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> List[Delivery]:
    """Liefert die Historie aller Webhook-Auslieferungen."""
    query = select(Delivery)
    if subscription_id:
        query = query.where(Delivery.subscription_id == subscription_id)
    if event_id:
        query = query.where(Delivery.event_id == event_id)
    if status_code is not None:
        query = query.where(Delivery.status_code == status_code)

    query = query.order_by(Delivery.delivered_at.desc().nulls_first(), Delivery.id.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/{delivery_id}/retry", response_model=DeliveryResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_delivery(
    delivery_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Delivery:
    """Sendet eine fehlgeschlagene Auslieferung manuell neu (Dead-Letter-Queue Re-Drive)."""
    stmt = select(Delivery).where(Delivery.id == delivery_id)
    result = await db.execute(stmt)
    delivery = result.scalar_one_or_none()

    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery mit ID {delivery_id} nicht gefunden",
        )

    # Reset delivery status for re-drive
    delivery.status_code = None
    delivery.response_body = "Re-queued via DLQ retry endpoint"
    delivery.attempt = 0
    await db.commit()
    await db.refresh(delivery)

    # Enqueue in background dispatcher
    await dispatcher.enqueue_delivery(delivery.id)

    return delivery
