from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any

from app.db.session import get_db
from app.models.webhook import Subscription
from app.schemas.webhook import EventPublish
from app.core.queue import webhook_queue, WebhookTask

router = APIRouter(prefix="/events", tags=["events"])

@router.post("/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish_event(
    event_in: EventPublish,
    db: AsyncSession = Depends(get_db)
):
    # Find all active subscriptions that match the event_type
    # Since event_types is a JSON list, we can query it.
    # In SQLite, JSON querying might be limited, so we can fetch all active and filter in Python,
    # or use SQLite JSON functions if available. For simplicity and reliability, we fetch active and filter.
    result = await db.execute(select(Subscription).where(Subscription.is_active == True))
    active_subs = result.scalars().all()
    
    matched_subs = []
    for sub in active_subs:
        if event_in.event_type in sub.event_types:
            matched_subs.append(sub)
            
    if not matched_subs:
        return {"message": "Event published, but no matching subscriptions found", "matched_count": 0}
        
    # Enqueue tasks
    for sub in matched_subs:
        task = WebhookTask(
            subscription_id=sub.id,
            event_id=event_in.event_id,
            payload=event_in.payload,
            secret=sub.secret,
            target_url=sub.target_url
        )
        await webhook_queue.put(task)
        
    return {"message": "Event published and tasks enqueued", "matched_count": len(matched_subs)}
