from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WebhookEndpointCreate(BaseModel):
    url: str
    secret: str | None = None
    description: str | None = None
    is_active: bool = True

class WebhookEndpointOut(BaseModel):
    id: UUID
    url: str
    secret: str | None = None
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
