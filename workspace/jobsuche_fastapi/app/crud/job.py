# app/crud/job.py
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import select, or_, and_
from app.models.job import Job
from typing import List, Optional

async def create_job(session: AsyncSession, job_data) -> Job:
    job = Job.from_orm(job_data)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job

async def get_job(session: AsyncSession, job_id: int) -> Optional[Job]:
    return await session.get(Job, job_id)

async def search_jobs(session: AsyncSession, filter_data) -> List[Job]:
    stmt = select(Job)

    if filter_data.query:
        q = f"%{filter_data.query.lower()}%"
        stmt = stmt.where(
            or_(
                Job.title.ilike(q),
                Job.description.ilike(q),
                Job.company.ilike(q),
                Job.industry.ilike(q),
            )
        )
    if filter_data.location:
        stmt = stmt.where(Job.location == filter_data.location)
    if filter_data.industry:
        stmt = stmt.where(Job.industry == filter_data.industry)
    if filter_data.experience_level:
        stmt = stmt.where(Job.experience_level == filter_data.experience_level)
    if filter_data.contract_type:
        stmt = stmt.where(Job.contract_type == filter_data.contract_type)

    stmt = stmt.offset(filter_data.skip).limit(filter_data.limit)
    result = await session.exec(stmt)
    return result.all()
