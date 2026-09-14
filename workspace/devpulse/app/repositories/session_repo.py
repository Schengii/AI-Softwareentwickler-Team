from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session


class SessionRepository:
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def create(self, project_id: int, start_time: datetime | None = None, end_time: datetime | None = None, note: str | None = None) -> Session:
        kwargs = {"project_id": project_id, "end_time": end_time, "note": note}
        if start_time is not None:
            kwargs["start_time"] = start_time
            
        session = Session(**kwargs)
        self.db_session.add(session)
        await self.db_session.commit()
        await self.db_session.refresh(session)
        return session
