from fastapi import Depends, FastAPI, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.kafka_client import KafkaProducerManager
from app.models import WebhookEvent
from app.resilience import ResilienceManager
from app.schemas import EventResponse, WebhookCreate
from app.security import SecurityMiddleware, verify_signature

app = FastAPI()
kafka_manager = KafkaProducerManager()
resilience = ResilienceManager()

@app.on_event("startup")
async def startup():
    await kafka_manager.start()

@app.on_event("shutdown")
async def shutdown():
    await kafka_manager.stop()

app.add_middleware(SecurityMiddleware)

@app.post("/api/v1/events", response_model=EventResponse)
async def create_event(
    event: WebhookCreate,
    request: Request,
    is_authorized: bool = Depends(verify_signature),
    db: AsyncSession = Depends(get_db)
):
    event_data = event.model_dump()
    
    @resilience.retry_with_backoff(retries=3)
    @resilience.circuit_breaker
    async def send_with_resilience():
        await kafka_manager.send_event("webhooks", event_data)

    try:
        await send_with_resilience()
        status_val = "published"
    except Exception:
        # Fallback to DB
        new_event = WebhookEvent(event_type=event.event_type, payload=event_data, status="failed_to_publish")
        db.add(new_event)
        await db.commit()
        status_val = "persisted_to_db"
    
    return {"id": 1, "status": status_val, **event_data}

@app.get("/api/v1/events", response_model=list[EventResponse])
async def get_events(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WebhookEvent).limit(50))
    events = result.scalars().all()
    return [EventResponse(id=e.id, event_type=e.event_type, payload=e.payload, status=e.status) for e in events]

@app.get("/api/v1/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count(WebhookEvent.id), WebhookEvent.status).group_by(WebhookEvent.status))
    stats = result.all()
    return {status: count for count, status in stats}
