from datetime import datetime

from pydantic import BaseModel


class TelemetryIngest(BaseModel):
    device_id: str
    metric: str
    value: float
    timestamp: datetime | None = None

class TelemetryResponse(BaseModel):
    id: int
    device_id: str
    metric: str
    value: float
    timestamp: datetime
    is_anomaly: bool
    z_score: float | None = None
    
    model_config = {"from_attributes": True}

class TelemetryStats(BaseModel):
    total_count: int
    anomaly_count: int
