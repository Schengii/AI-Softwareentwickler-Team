"""SQLAlchemy-Modelle für das AegisMesh API Gateway.

Definiert persistente Entitäten für Client-Verwaltung, Request-Auditing und Blocklisten.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def utc_now() -> datetime:
    """Gibt den aktuellen UTC-Zeitstempel zurück."""
    return datetime.now(timezone.utc)


class Client(Base):
    """Repräsentiert einen registrierten API-Client bzw. Mandanten."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_hash: Mapped[str | None] = mapped_column(String(256), nullable=True, default=None)
    tier: Mapped[str] = mapped_column(String(32), default="standard", nullable=False)
    custom_rate_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        Index("ix_clients_tier_active", "tier", "is_active"),
    )


class RequestAuditLog(Base):
    """Protokolliert bewertete Gateway-Anfragen für Security-Audits und ML-Training."""

    __tablename__ = "request_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    path: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    client_ip: Mapped[str] = mapped_column(String(45), index=True, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    action_taken: Mapped[str] = mapped_column(String(32), default="allowed", nullable=False)
    payload_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    headers_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True, nullable=False
    )

    __table_args__ = (
        Index("ix_audit_client_created", "client_id", "created_at"),
        Index("ix_audit_anomaly", "is_anomaly", "created_at"),
    )


class BlocklistEntry(Base):
    """Verwaltet gesperrte IP-Adressen oder Clients bei erkanntem Missbrauch."""

    __tablename__ = "blocklist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'ip' oder 'client'
    entity_value: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        Index("ix_blocklist_lookup", "entity_type", "entity_value", "is_active"),
    )
