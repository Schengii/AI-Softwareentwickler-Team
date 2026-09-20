import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.core.circuit_breaker import circuit_breaker_registry
from app.core.event_bus import Event, event_bus

logger = logging.getLogger(__name__)

router = APIRouter()

class EventCreate(BaseModel):
    type: str
    payload: dict[str, Any]

class EventResponse(BaseModel):
    status: str
    event_id: str

# In-memory store for events to ensure persistence
_events_store: dict[str, Event] = {}

@router.post("/", response_model=EventResponse)
async def create_event(
    event_in: EventCreate,
    x_idempotency_key: str | None = Header(None)
) -> EventResponse:
    # Circuit breaker check for upstream simulation
    breaker = await circuit_breaker_registry.get_breaker("event_upstream")
    
    # Simulate upstream call that might fail if circuit is open
    async def _simulate_upstream() -> None:
        pass # In a real scenario, this would call an external service
        
    await breaker.call(_simulate_upstream)
    
    event = Event(type=event_in.type, payload=event_in.payload)
    
    # Persist event
    _events_store[event.id] = event
    logger.info(f"Event created and persisted: {event.id}")
    
    await event_bus.publish(event)
    
    return EventResponse(status="accepted", event_id=event.id)

@router.get("/dlq")
async def get_dead_letter_queue() -> dict[str, Any]:
    dlq = event_bus.get_dlq()
    return {"dlq": [item.model_dump() for item in dlq]}

@router.get("/{event_id}", response_model=Event)
async def get_event(event_id: str) -> Event:
    if event_id in _events_store:
        return _events_store[event_id]
    raise HTTPException(status_code=404, detail="Event not found")
