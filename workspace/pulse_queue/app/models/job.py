import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import String, Integer, DateTime, JSON, Enum
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel, ConfigDict, Field
from app.core.database import Base
import enum

class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"

class JobType(str, enum.Enum):
    email_dispatch = "email_dispatch"
    data_export = "data_export"
    webhook_ping = "webhook_ping"

class JobModel(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, default=JobStatus.pending)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class JobCreate(BaseModel):
    type: JobType
    priority: int = Field(default=3, ge=1, le=5)
    payload: Dict[str, Any] = Field(default_factory=dict)

class JobResponse(BaseModel):
    id: str
    type: JobType
    priority: int
    status: JobStatus
    payload: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
