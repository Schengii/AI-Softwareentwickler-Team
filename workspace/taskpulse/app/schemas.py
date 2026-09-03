from datetime import datetime

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class TaskResponse(BaseModel):
    id: int
    name: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class EndpointStatusResponse(BaseModel):
    id: int
    url: str
    status_code: int
    response_time: float
    timestamp: datetime

    class Config:
        from_attributes = True

class CheckRequest(BaseModel):
    url: str = Field(..., pattern=r'^https?://')
