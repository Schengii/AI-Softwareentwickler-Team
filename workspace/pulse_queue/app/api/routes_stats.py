from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_async_session
from app.core.security import get_api_key
from app.services.queue_engine import queue_engine

router = APIRouter(tags=["stats"])

@router.get("/stats")
async def get_stats(
    session: AsyncSession = Depends(get_async_session),
    api_key: str = Depends(get_api_key)
):
    stats = await queue_engine.get_stats(session)
    return stats
