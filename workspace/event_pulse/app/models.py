import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Endpoint(Base):
    __tablename__ = "endpoints"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    url: Mapped[str] = mapped_column(String, nullable=False)
    secret: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deliveries: Mapped[list["Delivery"]] = relationship(back_populates="endpoint", cascade="all, delete-orphan")

class Event(Base):
    __tablename__ = "events"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deliveries: Mapped[list["Delivery"]] = relationship(back_populates="event", cascade="all, delete-orphan")

class Delivery(Base):
    __tablename__ = "deliveries"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True, nullable=False)
    endpoint_id: Mapped[str] = mapped_column(ForeignKey("endpoints.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", index=True) # pending, success, failed
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None, index=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    event: Mapped["Event"] = relationship(back_populates="deliveries")
    endpoint: Mapped["Endpoint"] = relationship(back_populates="deliveries")

    __table_args__ = (
        Index("ix_delivery_status_next_attempt", "status", "next_attempt"),
    )
