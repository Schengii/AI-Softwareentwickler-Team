from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MetricItem(BaseModel):
    """Schema für einen einzelnen Metrik-Datenpunkt."""
    name: str = Field(..., description="Name der Metrik, z.B. cpu_usage oder http_requests")
    value: float = Field(..., description="Numerischer Messwert")
    timestamp: float = Field(default_factory=lambda: datetime.utcnow().timestamp(), description="Unix-Zeitstempel in Sekunden")
    tags: Dict[str, str] = Field(default_factory=dict, description="Optionale Dimensionen/Labels")
    is_error: bool = Field(default=False, description="Flag ob der Datenpunkt einen Fehler repräsentiert")


class MetricBatch(BaseModel):
    """Schema für Batch-Ingestion mehrerer Metrik-Datenpunkte."""
    metrics: List[MetricItem] = Field(..., description="Liste von Metrik-Datenpunkten")


class WindowAggregate(BaseModel):
    """Aggregierte Kennzahlen für ein gleitendes Zeitfenster."""
    metric_name: str
    window_seconds: float
    count: int = 0
    throughput: float = 0.0
    error_rate: float = 0.0
    min: float = 0.0
    max: float = 0.0
    avg: float = 0.0
    sum: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0


class AlertRuleCreate(BaseModel):
    """Schema zur Erstellung einer neuen Alert-Regel."""
    id: Optional[str] = Field(default=None, description="Eindeutige ID der Regel (wird generiert falls nicht angegeben)")
    name: str = Field(..., description="Bezeichnung der Alert-Regel")
    metric_name: str = Field(..., description="Name der zu überwachenden Metrik")
    aggregation: str = Field(default="avg", description="Aggregationsfunktion: avg, p50, p95, p99, max, min, sum, count, error_rate")
    condition: str = Field(..., description="Vergleichsoperator: gt, gte, lt, lte, eq, ne")
    threshold: float = Field(..., description="Schwellwert für die Regelauslösung")
    window_seconds: float = Field(default=60.0, description="Zeitfenster in Sekunden")
    enabled: bool = Field(default=True, description="Status ob die Regel aktiv ist")


class AlertRule(AlertRuleCreate):
    """Persistierte Alert-Regel."""
    id: str = Field(..., description="Eindeutige ID der Regel")
    created_at: float = Field(default_factory=lambda: datetime.utcnow().timestamp())


class AlertEvent(BaseModel):
    """Ausgelöstes Alert-Ereignis."""
    id: str
    rule_id: str
    rule_name: str
    metric_name: str
    current_value: float
    threshold: float
    condition: str
    triggered_at: float
    status: str = "firing"  # firing / resolved
