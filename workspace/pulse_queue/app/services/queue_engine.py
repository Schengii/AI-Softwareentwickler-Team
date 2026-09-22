import asyncio
import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import async_session_maker
from app.models.job import JobModel, JobStatus, JobCreate

logger = logging.getLogger(__name__)

class QueueEngine:
    def __init__(self):
        self._stop_event = asyncio.Event()
        self.is_running = False
        self.sleep_interval = 2.0

    async def start(self):
        self.is_running = True
        self._stop_event.clear()
        asyncio.create_task(self._worker_loop())

    async def stop(self):
        self.is_running = False
        self._stop_event.set()

    async def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                await self._process_next_job()
            except Exception as e:
                logger.error(f"Worker error: {e}")
            
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.sleep_interval)
            except asyncio.TimeoutError:
                pass

    async def _process_next_job(self):
        async with async_session_maker() as session:
            # Find next pending job, priority 1 is highest (asc)
            stmt = select(JobModel).where(JobModel.status == JobStatus.pending).order_by(JobModel.priority.asc(), JobModel.created_at.asc()).limit(1)
            result = await session.execute(stmt)
            job = result.scalar_one_or_none()

            if not job:
                return

            # Mark as running
            job.status = JobStatus.running
            job.started_at = datetime.utcnow()
            await session.commit()
            
            job_id = job.id
            job_type = job.type
            payload = job.payload

        # Process job outside of the initial transaction
        try:
            # Simulate work
            await asyncio.sleep(0.5)
            
            result_data = {"processed": True, "type": job_type}
            
            async with async_session_maker() as session:
                stmt = select(JobModel).where(JobModel.id == job_id)
                res = await session.execute(stmt)
                job = res.scalar_one()
                job.status = JobStatus.completed
                job.completed_at = datetime.utcnow()
                job.result = result_data
                await session.commit()
        except Exception as e:
            async with async_session_maker() as session:
                stmt = select(JobModel).where(JobModel.id == job_id)
                res = await session.execute(stmt)
                job = res.scalar_one()
                job.status = JobStatus.failed
                job.completed_at = datetime.utcnow()
                job.error_message = str(e)
                await session.commit()

    async def create_job(self, session: AsyncSession, job_in: JobCreate) -> JobModel:
        job = JobModel(
            type=job_in.type,
            priority=job_in.priority,
            payload=job_in.payload
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    async def get_jobs(self, session: AsyncSession, status: Optional[JobStatus] = None, limit: int = 100, offset: int = 0) -> List[JobModel]:
        stmt = select(JobModel)
        if status:
            stmt = stmt.where(JobModel.status == status)
        stmt = stmt.order_by(JobModel.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_job(self, session: AsyncSession, job_id: str) -> Optional[JobModel]:
        stmt = select(JobModel).where(JobModel.id == job_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def cancel_job(self, session: AsyncSession, job_id: str) -> bool:
        stmt = select(JobModel).where(JobModel.id == job_id)
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        
        if not job or job.status != JobStatus.pending:
            return False
            
        job.status = JobStatus.failed
        job.error_message = "Cancelled by user"
        job.completed_at = datetime.utcnow()
        await session.commit()
        return True

    async def get_stats(self, session: AsyncSession) -> dict:
        stmt = select(JobModel.status, func.count(JobModel.id)).group_by(JobModel.status)
        result = await session.execute(stmt)
        counts = {status.value: 0 for status in JobStatus}
        for row in result:
            counts[row[0].value] = row[1]
            
        # Calculate average runtime
        stmt_avg = select(func.avg(
            func.julianday(JobModel.completed_at) - func.julianday(JobModel.started_at)
        )).where(JobModel.status == JobStatus.completed)
        avg_result = await session.execute(stmt_avg)
        avg_days = avg_result.scalar()
        avg_runtime_seconds = (avg_days * 86400) if avg_days else 0.0

        return {
            "counts": counts,
            "average_runtime_seconds": avg_runtime_seconds
        }

queue_engine = QueueEngine()
