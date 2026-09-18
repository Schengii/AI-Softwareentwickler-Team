import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DLQ = "DLQ"

def utcnow():
    return datetime.now(timezone.utc)

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    dependencies: Mapped[list["JobDependency"]] = relationship(
        "JobDependency",
        foreign_keys="[JobDependency.child_job_id]",
        back_populates="child_job",
        cascade="all, delete-orphan"
    )
    dependents: Mapped[list["JobDependency"]] = relationship(
        "JobDependency",
        foreign_keys="[JobDependency.parent_job_id]",
        back_populates="parent_job",
        cascade="all, delete-orphan"
    )
    dlq_entry: Mapped["DeadLetterQueue | None"] = relationship(
        "DeadLetterQueue",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_jobs_status_priority", "status", "priority"),
        Index("ix_jobs_created_at", "created_at"),
    )

class JobDependency(Base):
    __tablename__ = "job_dependencies"

    parent_job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    child_job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)

    parent_job: Mapped["Job"] = relationship("Job", foreign_keys=[parent_job_id], back_populates="dependents")
    child_job: Mapped["Job"] = relationship("Job", foreign_keys=[child_job_id], back_populates="dependencies")

    __table_args__ = (
        UniqueConstraint("parent_job_id", "child_job_id", name="uq_job_dependency"),
        Index("ix_job_dependencies_child", "child_job_id"),
    )

class DeadLetterQueue(Base):
    __tablename__ = "dead_letter_queue"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    job: Mapped["Job"] = relationship("Job", back_populates="dlq_entry")

    __table_args__ = (
        Index("ix_dlq_failed_at", "failed_at"),
    )
