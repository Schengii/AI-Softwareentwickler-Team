from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class MetricRecord(BaseModel):
    name: str = Field(..., description="Name der Metrik, z.B. cpu_usage, latency_ms")
    value: float = Field(..., description="Numerischer Messwert")
    timestamp: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp(),
        description="Unix-Timestamp der Messung in Sekunden"
    )
    tags: dict[str, str] = Field(default_factory=dict, description="Zusätzliche Labels/Dimensionen")

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "request_latency",
                "value": 42.5,
                "timestamp": 1700000000.0,
                "tags": {"service": "api-gateway", "env": "prod"}
            }
        }
    }


class WindowAggregate(BaseModel):
    name: str
    window_seconds: int
    count: int
    sum: float
    min: float
    max: float
    avg: float
    p95: float | None = None
    latest_value: float
    timestamp: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    tags: dict[str, str] = Field(default_factory=dict)


class BroadcastEvent(BaseModel):
    type: str  # "metric", "aggregate", "alert"
    timestamp: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp()
    )
    data: dict[str, Any]
