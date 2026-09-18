from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.job import JobStatus


class JobCreate(BaseModel):
    name: str
    payload: dict[str, Any] | None = None
    max_retries: int = Field(default=3, ge=0)
    priority: int = Field(default=0)
    parent_job_ids: list[str] = Field(default_factory=list)

class JobOut(BaseModel):
    id: str
    name: str
    status: JobStatus
    payload: dict[str, Any] | None = None
    retry_count: int
    max_retries: int
    priority: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class DLQOut(BaseModel):
    id: str
    job_id: str
    reason: str
    failed_at: datetime
    payload: dict[str, Any] | None = None

    model_config = {"from_attributes": True}
