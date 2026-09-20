# app/schemas/events.py
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventPayload(BaseModel):
    event_type: str = Field(..., description="Art des Events")
    data: dict[str, Any] = Field(..., description="Nutzdaten")

class EventResponse(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    status: str
