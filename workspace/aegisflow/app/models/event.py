import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# SQLAlchemy Models
class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String, index=True)
    idempotency_key: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="RECEIVED") # RECEIVED, DISPATCHED, FAILED, DEAD_LETTERED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class AuditLogRecord(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    old_status: Mapped[str | None] = mapped_column(String, nullable=True)
    new_status: Mapped[str] = mapped_column(String)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    details: Mapped[str | None] = mapped_column(String, nullable=True)

# Pydantic Schemas
class EventCreate(BaseModel):
    topic: str = Field(..., description="The topic to publish the event to")
    idempotency_key: str = Field(..., description="Unique key for idempotency within 15 minutes")
    payload: dict[str, Any] = Field(..., description="The event payload")

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, v):
        if len(json.dumps(v).encode("utf-8")) > 65536:
            raise ValueError("Payload exceeds 64KB limit")
        return v

class EventResponse(BaseModel):
    id: int
    topic: str
    idempotency_key: str
    status: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
