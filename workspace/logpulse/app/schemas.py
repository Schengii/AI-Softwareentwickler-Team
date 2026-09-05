from datetime import datetime

from pydantic import BaseModel


class LogEntryBase(BaseModel):
    level: str
    source: str
    message: str

class LogEntryCreate(LogEntryBase):
    pass

class LogEntryResponse(LogEntryBase):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True
