import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


def utcnow():
    return datetime.now(timezone.utc)

class Endpoint(Base):
    __tablename__ = "endpoints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String, nullable=False)
    secret = Column(String, nullable=True)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    delivery_logs = relationship("DeliveryLog", back_populates="endpoint", cascade="all, delete-orphan")
    idempotency_keys = relationship("IdempotencyKey", back_populates="endpoint", cascade="all, delete-orphan")


class DeliveryLog(Base):
    __tablename__ = "delivery_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint_id = Column(UUID(as_uuid=True), ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending, success, failed, dead_letter
    status_code = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    endpoint = relationship("Endpoint", back_populates="delivery_logs")

    __table_args__ = (
        Index("ix_delivery_logs_endpoint_id", "endpoint_id"),
        Index("ix_delivery_logs_status", "status"),
        Index("ix_delivery_logs_next_retry_at", "next_retry_at"),
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String, nullable=False)
    endpoint_id = Column(UUID(as_uuid=True), ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False)
    payload_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    endpoint = relationship("Endpoint", back_populates="idempotency_keys")

    __table_args__ = (
        UniqueConstraint("key", "endpoint_id", name="uq_idempotency_key_endpoint"),
        Index("ix_idempotency_keys_key", "key"),
        Index("ix_idempotency_keys_endpoint_id", "endpoint_id"),
    )
