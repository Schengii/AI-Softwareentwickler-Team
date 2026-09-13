"""SQLAlchemy 2.0 Modelle für Outbox-Events und Dead-Letter-Queue (DLQ)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class OutboxEvent(Base):
    """Transaktionale Outbox-Tabelle für garantierte At-Least-Once Delivery."""

    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=lambda: str(uuid.uuid4())
    )
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    destination_url: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Optionale Felder explizit mit nullable=True und default=None
    headers: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, native_enum=False, length=32),
        default=OutboxStatus.PENDING,
        index=True,
        nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    __table_args__ = (
        Index("ix_outbox_pending_dispatch", "status", "next_retry_at", "created_at"),
    )


class DeadLetterQueueEvent(Base):
    """Dead-Letter-Queue (DLQ) für endgültig fehlgeschlagene Events nach Expiry."""

    __tablename__ = "dead_letter_queue"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    original_event_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    destination_url: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Optionale Felder
    headers: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    
    total_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    
    moved_to_dlq_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    __table_args__ = (
        Index("ix_dlq_unresolved", "resolved", "moved_to_dlq_at"),
    )
