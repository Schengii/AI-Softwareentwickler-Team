"""HookSentinel - Asynchrone Datenbank-Architektur und SQLAlchemy-Modelle.

Dieses Modul stellt die SQLite/aiosqlite Engine mit WAL-Modus, die asynchrone
Session-Verwaltung und die vollständigen relationalen Modelle für Quellen,
Webhook-Events, Zustellversuche und die Dead-Letter-Queue (DLQ) bereit.
"""

from __future__ import annotations

import datetime
import enum
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

# ---------------------------------------------------------------------------
# Konfiguration & Datenbank-URL
# ---------------------------------------------------------------------------
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./hooksentinel.db")

# Async Engine konfigurieren
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

# SQLite WAL-Modus und Foreign Keys per Event Listener aktivieren
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """Aktiviert WAL-Modus, synchrone Optimierungen und Foreign-Key-Prüfungen."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()

# Asynchroner Session-Maker
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency für asynchrone Datenbank-Sessions."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Basis-Modell & Enums
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Zentrale DeclarativeBase für alle HookSentinel-Tabellen."""


class EventStatus(str, enum.Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    DLQ = "dlq"


class DLQErrorType(str, enum.Enum):
    HTTP_STATUS = "http_status"
    TIMEOUT = "timeout"
    TLS_ERROR = "tls_error"
    CIRCUIT_OPEN = "circuit_open"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Relationale Tabellen-Definitionen
# ---------------------------------------------------------------------------
class Source(Base):
    """Webhook-Quelle / Ingestion-Endpoint."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # HMAC Secret ist optional - falls leer, wird keine HMAC-Prüfung erzwungen
    secret: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None
    )
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    # Beziehungen
    events: Mapped[list[WebhookEvent]] = relationship(
        "WebhookEvent", back_populates="source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Source(id='{self.id}', slug='{self.slug}', active={self.is_active})>"


class WebhookEvent(Base):
    """Empfangenes Webhook-Event mit Payload, Status und Idempotenz."""

    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Idempotenz-Schlüssel: verhindert Mehrfachannahme identischer Webhooks
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True, default=None
    )
    event_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    headers: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus),
        default=EventStatus.PENDING,
        nullable=False,
        index=True,
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_retry_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    # Beziehungen
    source: Mapped[Source] = relationship("Source", back_populates="events")
    delivery_attempts: Mapped[list[DeliveryAttempt]] = relationship(
        "DeliveryAttempt", back_populates="event", cascade="all, delete-orphan",
        order_by="DeliveryAttempt.attempt_number"
    )
    dlq_entry: Mapped[DeadLetterEntry | None] = relationship(
        "DeadLetterEntry", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Index für den Relay-Dispatcher: schnelles Auffinden ausstehender Events
        Index("idx_events_status_next_retry", "status", "next_retry_at"),
        Index("idx_events_source_created", "source_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent(id='{self.id}', status='{self.status}', retries={self.retry_count})>"


class DeliveryAttempt(Base):
    """Zustellversuch eines Webhook-Events an das Zielsystem."""

    __tablename__ = "delivery_attempts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("webhook_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status_code: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None, index=True
    )
    response_body: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    duration_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False, index=True
    )

    # Beziehungen
    event: Mapped[WebhookEvent] = relationship(
        "WebhookEvent", back_populates="delivery_attempts"
    )

    __table_args__ = (
        Index("idx_delivery_event_attempt", "event_id", "attempt_number"),
    )

    def __repr__(self) -> str:
        return f"<DeliveryAttempt(id='{self.id}', event_id='{self.event_id}', status={self.status_code})>"


class DeadLetterEntry(Base):
    """Dead-Letter-Queue (DLQ) Eintrag nach Erschöpfung aller Retries."""

    __tablename__ = "dead_letter_entries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("webhook_events.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    error_type: Mapped[DLQErrorType] = mapped_column(
        Enum(DLQErrorType),
        default=DLQErrorType.UNKNOWN,
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    headers_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    replayed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    replay_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False, index=True
    )

    # Beziehungen
    event: Mapped[WebhookEvent] = relationship(
        "WebhookEvent", back_populates="dlq_entry"
    )

    def __repr__(self) -> str:
        return f"<DeadLetterEntry(id='{self.id}', event_id='{self.event_id}', error_type='{self.error_type}')>"


# ---------------------------------------------------------------------------
# Initialisierungs- & Lifecycle-Funktionen
# ---------------------------------------------------------------------------
async def init_db() -> None:
    """Erstellt alle Tabellen asynchron über die AsyncEngine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Schließt die Engine-Verbindungen sauber (z. B. beim Shutdown)."""
    await engine.dispose()
