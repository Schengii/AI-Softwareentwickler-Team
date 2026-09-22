import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DeliveryStatus, EventType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventModel(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=True,
        default=None,
    )
    metadata_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )

    delivery_attempts: Mapped[List["DeliveryAttemptModel"]] = relationship(
        "DeliveryAttemptModel",
        back_populates="event",
        cascade="all, delete-orphan",
    )


class SubscriptionModel(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    target_url: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    event_types: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    secret: Mapped[Optional[str]] = mapped_column(
        String(256),
        nullable=True,
        default=None,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        index=True,
        nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        default=10,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )

    delivery_attempts: Mapped[List["DeliveryAttemptModel"]] = relationship(
        "DeliveryAttemptModel",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )


class DeliveryAttemptModel(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("events.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    subscription_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=DeliveryStatus.PENDING.value,
        index=True,
        nullable=False,
    )
    status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )
    response_body: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )

    event: Mapped["EventModel"] = relationship(
        "EventModel",
        back_populates="delivery_attempts",
    )
    subscription: Mapped["SubscriptionModel"] = relationship(
        "SubscriptionModel",
        back_populates="delivery_attempts",
    )

    __table_args__ = (
        Index("ix_delivery_event_sub", "event_id", "subscription_id"),
        Index("ix_delivery_status_created", "status", "created_at"),
    )


# Aliase für maximale Kompatibilität mit Teamkollegen
Event = EventModel
Subscription = SubscriptionModel
DeliveryAttempt = DeliveryAttemptModel
