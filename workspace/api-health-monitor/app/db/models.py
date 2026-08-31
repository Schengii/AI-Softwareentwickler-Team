# app/db/models.py
"""
SQLAlchemy‑Modelle für den Health‑Monitor.

Enthält:
- CheckConfig   – Konfiguration eines HTTP‑Checks
- CheckResult   – Ergebnis jedes einzelnen Checks
- AlertLog      – Historie gesendeter Alert‑Webhooks
"""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.orm import relationship
from .database import Base


class CheckConfig(Base):
    """Konfiguration eines zu überwachenden HTTP‑Endpoints."""

    __tablename__ = "check_config"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False, unique=True, comment="Zu prüfende URL")
    method = Column(String, nullable=False, default="GET", comment="HTTP‑Methode")
    interval_seconds = Column(
        Integer, nullable=False, comment="Intervall zwischen Checks (Sekunden)"
    )
    expected_status = Column(
        Integer, nullable=False, default=200, comment="Erwarteter HTTP‑Status"
    )

    # Beziehungen
    results = relationship(
        "CheckResult",
        back_populates="check",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    alerts = relationship(
        "AlertLog",
        back_populates="check",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CheckResult(Base):
    """Ein einzelner Durchlauf eines Checks."""

    __tablename__ = "check_result"

    id = Column(Integer, primary_key=True, index=True)
    check_id = Column(
        Integer,
        ForeignKey("check_config.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Zeitpunkt des Checks (UTC)",
    )
    response_time_ms = Column(
        Float, nullable=False, comment="Antwortzeit in Millisekunden"
    )
    status_code = Column(Integer, nullable=False, comment="HTTP‑Status des Responses")

    # Beziehung zurück zu CheckConfig
    check = relationship("CheckConfig", back_populates="results")

    # Index für häufige Abfragen nach Check + Zeit
    __table_args__ = (
        Index("idx_checkresult_check_timestamp", "check_id", "timestamp"),
    )


class AlertLog(Base):
    """Protokollierung gesendeter Alert‑Webhooks."""

    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True, index=True)
    check_id = Column(
        Integer,
        ForeignKey("check_config.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="Zeitpunkt des Alert‑Versands (UTC)",
    )
    payload = Column(
        JSON,
        nullable=True,
        comment="Gesendeter Payload (z. B. Discord/Slack‑Webhook‑Body)",
    )

    # Beziehung zurück zu CheckConfig
    check = relationship("CheckConfig", back_populates="alerts")

    __table_args__ = (
        Index("idx_alertlog_check_timestamp", "check_id", "timestamp"),
    )
