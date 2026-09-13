"""AetherMesh Engine - Jobs REST-API Router.

Verwaltet das Einreichen, Abfragen und Retrying von Jobs
unter Berücksichtigung von Prioritäten und Backpressure (HTTP 429).
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.db.models import JobStatus
from app.services.backpressure import BackpressureController
from app.services.queue import JobQueueManager


class JobPriority(str, Enum):
    """Prioritätsstufen für Jobs in der AetherMesh Engine."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


class JobCreateRequest(BaseModel):
    """Schema für die Einreichung eines neuen Jobs."""
    job_type: str = Field(..., description="Typ des Jobs, z.B. data_sync, image_resize")
    payload: dict[str, Any] = Field(default_factory=dict, description="Nutzdaten des Jobs")
    priority: JobPriority = Field(default=JobPriority.NORMAL, description="Priorität des Jobs")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximale Anzahl an Wiederholungen")


class JobResponse(BaseModel):
    """Schema für die Rückgabe eines Jobs."""
    id: str
    job_type: str
    payload: dict[str, Any]
    priority: JobPriority
    status: JobStatus
    attempts: int
    max_retries: int
    error_message: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: JobCreateRequest,
    response: Response,
) -> Any:
    """Reicht einen neuen Job in die Engine ein.
    
    Greift Backpressure (Queue zu voll), wird HTTP 429 Too Many Requests
    mit Retry-After Header zurückgegeben.
    """
    from app.main import backpressure_controller, queue_manager

    # Backpressure-Check (Admission Control)
    admitted, retry_after = backpressure_controller.check_admission()
    if not admitted:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Queue capacity exceeded. Backpressure active.",
            headers={"Retry-After": str(retry_after)},
        )

    job_id = str(uuid.uuid4())
    job = await queue_manager.enqueue_job(
        job_id=job_id,
        job_type=request.job_type,
        payload=request.payload,
        priority=request.priority,
        max_retries=request.max_retries,
    )
    return job


@router.get("", response_model=list[JobResponse])
@router.get("/", response_model=list[JobResponse])
async def list_jobs(
    status_filter: Optional[JobStatus] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Any:
    """Listet vorhandene Jobs mit optionalem Status-Filter auf."""
    from app.main import queue_manager
    return await queue_manager.get_jobs(status_filter=status_filter, limit=limit, offset=offset)


@router.get("/dlq", response_model=list[JobResponse])
async def get_dead_letter_queue(
    limit: int = Query(50, ge=1, le=500),
) -> Any:
    """Ruft Jobs aus der Dead-Letter-Queue (DLQ) ab."""
    from app.main import queue_manager
    return await queue_manager.get_dlq_jobs(limit=limit)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_by_id(job_id: str) -> Any:
    """Ruft die Details und den Status eines bestimmten Jobs ab."""
    from app.main import queue_manager
    job = await queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job mit ID {job_id} nicht gefunden.",
        )
    return job


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_failed_job(job_id: str) -> Any:
    """Reaktiviert einen fehlgeschlagenen DLQ-Job zur erneuten Ausführung."""
    from app.main import queue_manager
    retried_job = await queue_manager.retry_job(job_id)
    if not retried_job:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job {job_id} kann nicht erneut ausgeführt werden.",
        )
    return retried_job
