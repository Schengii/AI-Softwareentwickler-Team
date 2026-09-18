import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import not_, or_, select

from app.core.settings import get_settings
from app.db.session import AsyncSessionLocal
from app.models.job import DeadLetterQueue, Job, JobDependency, JobStatus

logger = logging.getLogger(__name__)
settings = get_settings()

async def execute_job(job: Job) -> None:
    # Dummy execution logic
    logger.info(f"Executing job {job.id} ({job.name})")
    # Simulate some work
    await asyncio.sleep(0.1)
    if job.name == "fail_always":
        raise ValueError("Simulated failure")
    if job.name == "fail_once" and job.retry_count == 0:
        raise ValueError("Simulated temporary failure")

async def process_jobs():
    async with AsyncSessionLocal() as db:
        # Find jobs that are PENDING
        # And either have no next_retry_at or next_retry_at <= now
        # And all their parent dependencies are COMPLETED
        now = datetime.now(timezone.utc)
        
        # Subquery to find jobs with uncompleted parents
        uncompleted_parents_subq = select(JobDependency.child_job_id).join(
            Job, Job.id == JobDependency.parent_job_id
        ).where(Job.status != JobStatus.COMPLETED)

        stmt = select(Job).where(
            Job.status == JobStatus.PENDING,
            or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now),
            not_(Job.id.in_(uncompleted_parents_subq))
        ).order_by(Job.priority.desc(), Job.created_at.asc()).limit(10)

        result = await db.execute(stmt)
        jobs = result.scalars().all()

        for job in jobs:
            job.status = JobStatus.RUNNING
            await db.commit()
            
            try:
                await execute_job(job)
                job.status = JobStatus.COMPLETED
                await db.commit()
            except Exception as e:
                logger.error(f"Job {job.id} failed: {e}")
                job.retry_count += 1
                job.error_message = str(e)
                
                if job.retry_count > job.max_retries:
                    job.status = JobStatus.DLQ
                    dlq_entry = DeadLetterQueue(
                        job_id=job.id,
                        reason=str(e),
                        payload=job.payload
                    )
                    db.add(dlq_entry)
                else:
                    job.status = JobStatus.PENDING
                    # Exponential backoff: 2^retry_count seconds
                    delay = 2 ** job.retry_count
                    job.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                
                await db.commit()

async def worker_loop():
    logger.info("Worker loop started")
    while True:
        try:
            await process_jobs()
        except asyncio.CancelledError:
            logger.info("Worker loop cancelled")
            break
        except Exception as e:
            logger.error(f"Error in worker loop: {e}")
        
        await asyncio.sleep(settings.WORKER_POLL_INTERVAL)
