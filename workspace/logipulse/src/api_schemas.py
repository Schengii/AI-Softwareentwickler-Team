from datetime import datetime

from pydantic import BaseModel


class MetricSummary(BaseModel):
    total_requests: int
    error_rate: float
    avg_latency_ms: float
    timestamp: datetime

class Anomaly(BaseModel):
    id: str
    description: str
    severity: str
    detected_at: datetime
    resolved: bool = False

class Trace(BaseModel):
    trace_id: str
    endpoint: str
    duration_ms: float
    status_code: int
    timestamp: datetime
