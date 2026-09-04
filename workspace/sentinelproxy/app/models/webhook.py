from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel


class WebhookEvent(BaseModel):
    id: UUID = uuid4()
    source: str
    data: dict[str, Any]
    received_at: datetime = datetime.utcnow()
