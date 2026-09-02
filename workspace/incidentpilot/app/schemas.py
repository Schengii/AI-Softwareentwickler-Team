from typing import Any

from pydantic import BaseModel, Field


class WebhookPayload(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=100)
    data: dict[str, Any]
