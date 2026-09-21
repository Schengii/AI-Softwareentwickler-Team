from datetime import UTC, datetime

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)

class MetricPoint(BaseModel):
    name: str
    value: float
    timestamp: datetime = Field(default_factory=utc_now)
    tags: dict[str, str] | None = None

class MetricStats(BaseModel):
    name: str
    count: int
    min: float
    max: float
    mean: float
    stddev: float
    p50: float
    p95: float
    p99: float

class Alert(BaseModel):
    id: str
    metric_name: str
    timestamp: datetime
    value: float
    z_score: float
    threshold: float
    message: str
