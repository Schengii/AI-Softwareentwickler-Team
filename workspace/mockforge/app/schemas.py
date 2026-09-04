
from pydantic import BaseModel


class MockCreate(BaseModel):
    method: str
    path_pattern: str
    response_status: int
    response_body: str
    is_active: bool = True

class MockResponse(MockCreate):
    id: int
    class Config:
        from_attributes = True

class TrafficLogResponse(BaseModel):
    id: int
    timestamp: str
    method: str
    url: str
    request_headers: str | None
    request_body: str | None
    response_status: int
    response_body: str | None
    class Config:
        from_attributes = True
