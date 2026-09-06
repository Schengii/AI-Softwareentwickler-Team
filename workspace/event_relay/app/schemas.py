from datetime import datetime
from typing import Any

from pydantic import BaseModel


class WebhookCreate(BaseModel):
    event_type: str
    payload: dict[str, Any]

class EventResponse(WebhookCreate):
    id: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
