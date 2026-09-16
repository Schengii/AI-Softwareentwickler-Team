from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1)
    url: HttpUrl
    interval_seconds: int = Field(default=60, ge=10)
    expected_status: int = Field(default=200, ge=100, le=599)
    timeout: int = Field(default=5, ge=1, le=60)

class MonitorResponse(MonitorCreate):
    id: int
    last_checked: datetime | None = None
    last_status_code: int | None = None
    last_latency_ms: float | None = None
    is_up: bool | None = None
    last_error: str | None = None

    model_config = ConfigDict(from_attributes=True)

class StatsResponse(BaseModel):
    total: int
    up: int
    down: int
    avg_latency_ms: float
