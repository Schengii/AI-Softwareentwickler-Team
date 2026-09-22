from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.core.database import get_async_session
from app.core.security import get_api_key
from app.models.job import JobCreate, JobResponse, JobStatus
from app.services.queue_engine import queue_engine

router = APIRouter(tags=["jobs"])

@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_in: JobCreate,
    session: AsyncSession = Depends(get_async_session),
    api_key: str = Depends(get_api_key)
):
    job = await queue_engine.create_job(session, job_in)
    return job

@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    status: Optional[JobStatus] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    api_key: str = Depends(get_api_key)
):
    jobs = await queue_engine.get_jobs(session, status=status, limit=limit, offset=offset)
    return jobs

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_async_session),
    api_key: str = Depends(get_api_key)
):
    job = await queue_engine.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    session: AsyncSession = Depends(get_async_session),
    api_key: str = Depends(get_api_key)
):
    success = await queue_engine.cancel_job(session, job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled (not found or not pending)")
    job = await queue_engine.get_job(session, job_id)
    return job
