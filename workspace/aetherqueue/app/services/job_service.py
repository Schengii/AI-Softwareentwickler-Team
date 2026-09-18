
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import DeadLetterQueue, Job, JobDependency, JobStatus
from app.schemas.job import JobCreate


class JobService:
    @staticmethod
    async def create_job(db: AsyncSession, job_in: JobCreate) -> Job:
        # Create the job
        job = Job(
            name=job_in.name,
            payload=job_in.payload,
            max_retries=job_in.max_retries,
            priority=job_in.priority,
            status=JobStatus.PENDING
        )
        db.add(job)
        await db.flush()  # To get the job.id

        # Create dependencies
        for parent_id in job_in.parent_job_ids:
            # Optionally check if parent exists
            dep = JobDependency(parent_job_id=parent_id, child_job_id=job.id)
            db.add(dep)
        
        await db.commit()
        await db.refresh(job)
        return job

    @staticmethod
    async def get_job(db: AsyncSession, job_id: str) -> Job | None:
        result = await db.execute(select(Job).where(Job.id == job_id))
        return result.scalars().first()

    @staticmethod
    async def list_jobs(db: AsyncSession, limit: int = 100, offset: int = 0) -> list[Job]:
        result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())

    @staticmethod
    async def get_dlq(db: AsyncSession, limit: int = 100, offset: int = 0) -> list[DeadLetterQueue]:
        result = await db.execute(select(DeadLetterQueue).order_by(DeadLetterQueue.failed_at.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())
