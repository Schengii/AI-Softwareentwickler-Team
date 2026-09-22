import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    event_types: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    deliveries: Mapped[List["Delivery"]] = relationship(
        "Delivery", back_populates="subscription", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_subscriptions_is_active", "is_active"),
    )

class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

    subscription: Mapped["Subscription"] = relationship("Subscription", back_populates="deliveries")

    __table_args__ = (
        Index("ix_deliveries_subscription_id", "subscription_id"),
        Index("ix_deliveries_event_id", "event_id"),
        Index("ix_deliveries_status_code", "status_code"),
    )
