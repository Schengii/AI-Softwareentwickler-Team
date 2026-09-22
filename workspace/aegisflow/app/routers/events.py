from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models.event import EventCreate, EventResponse
from app.services.event_service import EventService

router = APIRouter(prefix="/api/v1/events", tags=["Events"])

@router.post("", response_model=EventResponse, status_code=status.HTTP_200_OK)
@router.post("/", response_model=EventResponse, status_code=status.HTTP_200_OK)
async def publish_event(
    event_data: EventCreate,
    session: AsyncSession = Depends(get_async_session)
):
    service = EventService(session)
    return await service.process_event(event_data)

@router.get("/{event_id}", response_model=EventResponse, status_code=status.HTTP_200_OK)
async def get_event(
    event_id: str,
    session: AsyncSession = Depends(get_async_session)
):
    service = EventService(session)
    event = await service.get_event(event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event
