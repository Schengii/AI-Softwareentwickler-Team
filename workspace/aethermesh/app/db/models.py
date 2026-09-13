"""Datenbank-Modelle für AetherMesh (SQLAlchemy 2.0)."""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Zentrale Basisklasse für alle Datenbankmodelle."""
    pass


class JobStatus(str, Enum):
    """Mögliche Zustände eines Jobs."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DLQ = "dlq"


class Job(Base):
    """Persistiertes Job-Modell für SQLite-Spooling und Status-Tracking."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5, index=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING.value, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)


class DeadLetterRecord(Base):
    """Quarantäne-Archiv für dauerhaft fehlgeschlagene Jobs (DLQ)."""

    __tablename__ = "dead_letter_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    retry_attempts: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


# Alias für Kompatibilität
JobModel = Job

