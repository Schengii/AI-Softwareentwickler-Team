from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import EventCreate, EventResponse
from app.storage.event_repository import EventRepository


class EventService:
    def __init__(self, session: AsyncSession):
        self.repo = EventRepository(session)

    async def process_event(self, event_data: EventCreate) -> EventResponse:
        # Check idempotency
        existing_event = await self.repo.get_recent_event_by_idempotency_key(event_data.idempotency_key)
        if existing_event:
            return EventResponse.model_validate(existing_event)
        
        # Create new event
        new_event = await self.repo.create_event(event_data)
        return EventResponse.model_validate(new_event)
