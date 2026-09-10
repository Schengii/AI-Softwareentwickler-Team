from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    SENSOR_READING = "sensor_reading"
    SYSTEM_ALERT = "system_alert"
    TRANSACTION_UPDATE = "transaction_update"

class BaseEvent(BaseModel):
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: dict[str, Any]

class SensorReadingPayload(BaseModel):
    sensor_id: str
    value: float
    unit: str

class SystemAlertPayload(BaseModel):
    alert_level: str
    message: str
    component: str

class TransactionUpdatePayload(BaseModel):
    transaction_id: str
    status: str
    amount: float
