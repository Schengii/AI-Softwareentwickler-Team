
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.job import DLQOut, JobCreate, JobOut
from app.services.job_service import JobService

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])
dlq_router = APIRouter(prefix="/api", tags=["DLQ"])

@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(job_in: JobCreate, db: AsyncSession = Depends(get_db)):
    job = await JobService.create_job(db, job_in)
    return job

@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await JobService.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.get("", response_model=list[JobOut])
async def list_jobs(limit: int = 100, offset: int = 0, db: AsyncSession = Depends(get_db)):
    jobs = await JobService.list_jobs(db, limit, offset)
    return jobs

@dlq_router.get("", response_model=list[DLQOut])
async def list_dlq(limit: int = 100, offset: int = 0, db: AsyncSession = Depends(get_db)):
    dlq = await JobService.get_dlq(db, limit, offset)
    return dlq
