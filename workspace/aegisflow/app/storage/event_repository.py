from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import AuditLogRecord, EventCreate, EventRecord


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_recent_event_by_idempotency_key(self, idempotency_key: str, minutes: int = 15) -> EventRecord | None:
        time_threshold = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        stmt = select(EventRecord).where(
            EventRecord.idempotency_key == idempotency_key,
            EventRecord.created_at >= time_threshold
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_event(self, event_data: EventCreate) -> EventRecord:
        new_event = EventRecord(
            topic=event_data.topic,
            idempotency_key=event_data.idempotency_key,
            payload=event_data.payload,
            status="RECEIVED"
        )
        self.session.add(new_event)
        await self.session.flush() # To get the ID
        
        # Create audit log
        audit_log = AuditLogRecord(
            event_id=new_event.id,
            old_status=None,
            new_status="RECEIVED",
            details="Event ingested"
        )
        self.session.add(audit_log)
        await self.session.commit()
        await self.session.refresh(new_event)
        return new_event
