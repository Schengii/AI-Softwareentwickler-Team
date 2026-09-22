"""API-Routen für Events (v1).

Endpunkte zur Erfassung und Abfrage von Events sowie Auslösung von Webhook-Dispatches.
"""

from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.database import EventModel
from app.models.enums import EventType
from app.services.webhook_dispatcher import WebhookDispatcher

router = APIRouter(prefix="/api/v1/events", tags=["Events"])


# Pydantic Schemas
class EventCreate(BaseModel):
    """Schema zur Erstellung eines neuen Events."""
    event_type: str = Field(..., description="Typ des Events, z.B. user.created")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event-Nutzdaten als JSON-Objekt")
    source: Optional[str] = Field(default="api", description="Quelle des Events")


class EventResponse(BaseModel):
    """Schema für die Event-Antwort."""
    id: str
    event_type: str
    payload: Dict[str, Any]
    source: str
    created_at: str

    class Config:
        from_attributes = True


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    event_in: EventCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Erstellt ein neues Event, speichert es in der Datenbank und stößt asynchronen Dispatch an."""
    event_id = str(uuid.uuid4())
    db_event = EventModel(
        id=event_id,
        event_type=event_in.event_type,
        payload=event_in.payload,
        source=event_in.source or "api",
    )
    db.add(db_event)
    await db.commit()
    await db.refresh(db_event)

    # Webhook-Dispatch im Hintergrund anstoßen
    dispatcher = WebhookDispatcher()
    background_tasks.add_task(dispatcher.dispatch_event, event_id)

    return EventResponse(
        id=db_event.id,
        event_type=db_event.event_type,
        payload=db_event.payload or {},
        source=db_event.source,
        created_at=db_event.created_at.isoformat() if db_event.created_at else "",
    )


@router.get("", response_model=List[EventResponse])
async def list_events(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = Query(None, description="Optionaler Filter nach EventType"),
    db: AsyncSession = Depends(get_db),
):
    """Gibt eine Liste von Events mit Paginierung zurück."""
    query = select(EventModel).order_by(EventModel.created_at.desc()).offset(offset).limit(limit)
    if event_type:
        query = query.where(EventModel.event_type == event_type)

    result = await db.execute(query)
    events = result.scalars().all()

    return [
        EventResponse(
            id=ev.id,
            event_type=ev.event_type,
            payload=ev.payload or {},
            source=ev.source,
            created_at=ev.created_at.isoformat() if ev.created_at else "",
        )
        for ev in events
    ]


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Ruft ein spezifisches Event anhand seiner ID ab."""
    query = select(EventModel).where(EventModel.id == event_id)
    result = await db.execute(query)
    db_event = result.scalar_one_or_none()

    if not db_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event mit ID '{event_id}' wurde nicht gefunden.",
        )

    return EventResponse(
        id=db_event.id,
        event_type=db_event.event_type,
        payload=db_event.payload or {},
        source=db_event.source,
        created_at=db_event.created_at.isoformat() if db_event.created_at else "",
    )
