from datetime import datetime

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    service_id: str
    message: str
    level: str = "INFO"
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class IncidentCreate(BaseModel):
    title: str
    description: str
    severity: str = "MEDIUM"
    service_id: str
