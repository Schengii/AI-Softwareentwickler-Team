from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models.event import EventCreate, EventResponse
from app.services.event_service import EventService

router = APIRouter(prefix="/api/v1/events", tags=["Events"])

@router.post("", response_model=EventResponse, status_code=status.HTTP_200_OK)
async def publish_event(
    event_data: EventCreate,
    session: AsyncSession = Depends(get_async_session)
):
    service = EventService(session)
    return await service.process_event(event_data)
