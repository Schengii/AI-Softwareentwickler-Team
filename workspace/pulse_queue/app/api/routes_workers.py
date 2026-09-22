from fastapi import APIRouter, Depends
from app.core.security import get_api_key
from app.services.queue_engine import queue_engine

router = APIRouter(tags=["workers"])

@router.get("/workers/status")
async def get_worker_status(api_key: str = Depends(get_api_key)):
    return {
        "is_running": queue_engine.is_running,
        "sleep_interval": queue_engine.sleep_interval
    }
