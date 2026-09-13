"""SQLAlchemy 2.0 Datenmodelle für IncidentPulse."""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Gemeinsame deklarative Basisklasse für alle Datenbankmodelle."""


class IncidentStatus(str, enum.Enum):
    """Status-Workflow für Incidents."""
    # Spezifikation: Triaged -> In-Progress -> Mitigated -> Resolved (kompatibel mit open / investigating)
    OPEN = "open"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    IN_PROGRESS = "in-progress"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentSeverity(str, enum.Enum):
    """Priorität / Schweregrad von Incidents (P1-P4 sowie low/medium/high/critical)."""
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Many-to-Many Assoziationstabelle zwischen Incidents und Tags
incident_tags = Table(
    "incident_tags",
    Base.metadata,
    Column("incident_id", Integer, ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_incident_tags_incident_id", "incident_id"),
    Index("ix_incident_tags_tag_id", "tag_id"),
)


class Incident(Base):
    """Modell für Störungen und System-Incidents."""
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=IncidentStatus.OPEN.value,
        index=True,
    )
    severity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=IncidentSeverity.MEDIUM.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Beziehungen
    tags: Mapped[list["Tag"]] = relationship(
        "Tag",
        secondary=incident_tags,
        back_populates="incidents",
        lazy="selectin",
    )
    timeline_events: Mapped[list["TimelineEvent"]] = relationship(
        "TimelineEvent",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="TimelineEvent.created_at.asc()",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_incidents_status_severity", "status", "severity"),
        Index("ix_incidents_created_at_desc", created_at.desc()),
    )


class Tag(Base):
    """Modell für Tags zur Verschlagwortung von Incidents."""
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    incidents: Mapped[list["Incident"]] = relationship(
        "Incident",
        secondary=incident_tags,
        back_populates="tags",
        lazy="selectin",
    )


class TimelineEvent(Base):
    """Modell für Audit- & Fortschrittsereignisse eines Incidents."""
    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, default="status_change", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    incident: Mapped["Incident"] = relationship(
        "Incident",
        back_populates="timeline_events",
    )

    __table_args__ = (
        Index("ix_timeline_events_incident_created", "incident_id", "created_at"),
    )
