from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ServiceBase(BaseModel):
    name: str
    status: str

class ServiceRead(ServiceBase):
    id: int
    last_checked: datetime

    class Config:
        from_attributes = True

class IncidentBase(BaseModel):
    service_id: int
    title: str
    description: str

class IncidentRead(IncidentBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
