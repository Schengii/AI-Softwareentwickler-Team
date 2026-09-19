from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.security import check_idempotency, verify_signature
from app.db.models import DeliveryLog, Endpoint, IdempotencyKey
from app.schemas import WebhookEndpointCreate, WebhookEndpointOut

router = APIRouter()

@router.post("/endpoints", response_model=WebhookEndpointOut, status_code=201)
async def create_endpoint(
    endpoint_in: WebhookEndpointCreate,
    session: AsyncSession = Depends(get_db)
):
    new_endpoint = Endpoint(
        url=endpoint_in.url,
        secret=endpoint_in.secret,
        description=endpoint_in.description,
        is_active=endpoint_in.is_active
    )
    session.add(new_endpoint)
    await session.commit()
    await session.refresh(new_endpoint)
    return new_endpoint

@router.get("/endpoints", response_model=list[WebhookEndpointOut])
async def list_endpoints(
    session: AsyncSession = Depends(get_db)
):
    result = await session.execute(select(Endpoint))
    endpoints = result.scalars().all()
    return endpoints

@router.post("/ingest/{endpoint_id}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_webhook(
    endpoint_id: str,
    request: Request,
    endpoint = Depends(verify_signature),
    idempotency_key = Depends(check_idempotency),
    db: AsyncSession = Depends(get_db)
):
    payload = await request.json()
    
    new_log = DeliveryLog(endpoint_id=endpoint.id, payload=payload, status="pending")
    db.add(new_log)
    
    new_key = IdempotencyKey(key=idempotency_key, endpoint_id=endpoint.id)
    db.add(new_key)
    
    await db.commit()
    return {"status": "accepted"}
