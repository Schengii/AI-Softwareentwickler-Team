from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID

from app.db.session import get_db
from app.models.webhook import Subscription
from app.schemas.webhook import SubscriptionCreate, SubscriptionResponse

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    sub_in: SubscriptionCreate,
    db: AsyncSession = Depends(get_db)
):
    # Basic SSRF protection: prevent localhost or private IPs
    # For now, we rely on a simple string check or url parsing, but HttpUrl already does some validation.
    # We will add stricter SSRF validation in the service layer or here.
    url_str = str(sub_in.target_url)
    if "localhost" in url_str or "127.0.0.1" in url_str or "::1" in url_str:
        raise HTTPException(status_code=400, detail="Invalid target URL: local addresses are not allowed")

    new_sub = Subscription(
        target_url=url_str,
        secret=sub_in.secret,
        event_types=sub_in.event_types,
        is_active=True
    )
    db.add(new_sub)
    await db.commit()
    await db.refresh(new_sub)
    return new_sub

@router.get("", response_model=List[SubscriptionResponse])
async def list_subscriptions(
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Subscription).where(Subscription.is_active == True))
    subs = result.scalars().all()
    return subs
