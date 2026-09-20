import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, JSON, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class WorkflowDefinition(Base):
    """
    Schema/Regelwerk für Workflows.
    """
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    initial_state: Mapped[str] = mapped_column(String, nullable=False)
    states: Mapped[dict] = mapped_column(JSON, nullable=False)
    transitions: Mapped[dict] = mapped_column(JSON, nullable=False)

    instances: Mapped[list["WorkflowInstance"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan"
    )


class WorkflowInstance(Base):
    """
    Zustand einer konkreten Workflow-Ausführung.
    """
    __tablename__ = "workflow_instances"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), nullable=False, index=True)
    current_state: Mapped[str] = mapped_column(String, nullable=False, index=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    definition: Mapped["WorkflowDefinition"] = relationship(back_populates="instances")
    audit_logs: Mapped[list["AuditLogEntry"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", order_by="AuditLogEntry.sequence_number"
    )


class AuditLogEntry(Base):
    """
    Unveränderlicher Audit-Log-Eintrag mit kryptografischer Verkettung.
    """
    __tablename__ = "audit_log_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    instance_id: Mapped[str] = mapped_column(ForeignKey("workflow_instances.id"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_state: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    to_state: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload_hash: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    current_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    instance: Mapped["WorkflowInstance"] = relationship(back_populates="audit_logs")

    __table_args__ = (
        UniqueConstraint("instance_id", "sequence_number", name="uq_instance_sequence"),
    )
