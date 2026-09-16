import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Pipeline, PipelineRun, StepExecution
from app.schemas import StatsResponse


class RunService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(self, pipeline: Pipeline) -> PipelineRun:
        run = PipelineRun(
            pipeline_id=pipeline.id,
            status="PENDING",
        )
        self.session.add(run)
        await self.session.flush()

        # Step-Executions vorbereiten
        steps_data = pipeline.steps or []
        for index, step_dict in enumerate(steps_data):
            step_id = step_dict.get("id") or f"step-{uuid.uuid4().hex[:6]}"
            step_name = step_dict.get("name") or f"Step {index + 1}"
            step_type = step_dict.get("type", "shell")

            step_exec = StepExecution(
                run_id=run.id,
                step_id=step_id,
                name=step_name,
                type=step_type,
                order_index=index,
                status="PENDING",
                logs="",
            )
            self.session.add(step_exec)

        await self.session.commit()
        await self.session.refresh(run)
        return await self.get_run(run.id)

    async def get_run(self, run_id: int) -> PipelineRun | None:
        stmt = (
            select(PipelineRun)
            .options(selectinload(PipelineRun.step_executions))
            .where(PipelineRun.id == run_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pipeline_runs(self, pipeline_id: int) -> list[PipelineRun]:
        stmt = (
            select(PipelineRun)
            .options(selectinload(PipelineRun.step_executions))
            .where(PipelineRun.pipeline_id == pipeline_id)
            .order_by(PipelineRun.id.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_runs(self) -> list[PipelineRun]:
        stmt = (
            select(PipelineRun)
            .options(selectinload(PipelineRun.step_executions))
            .order_by(PipelineRun.id.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_run_cancelled(self, run_id: int) -> None:
        await self.session.execute(
            update(PipelineRun)
            .where(PipelineRun.id == run_id)
            .values(status="CANCELLED", error_message="Manuell abgebrochen.")
        )
        await self.session.execute(
            update(StepExecution)
            .where(StepExecution.run_id == run_id, StepExecution.status.in_(["PENDING", "RUNNING"]))
            .values(status="CANCELLED")
        )
        await self.session.commit()

    async def get_stats(self) -> StatsResponse:
        # 1. Total Pipelines
        pipelines_count = (await self.session.execute(select(func.count(Pipeline.id)))).scalar() or 0

        # 2. Total Runs & Status breakdown
        runs_count = (await self.session.execute(select(func.count(PipelineRun.id)))).scalar() or 0
        success_count = (await self.session.execute(
            select(func.count(PipelineRun.id)).where(PipelineRun.status == "SUCCESS")
        )).scalar() or 0
        failed_count = (await self.session.execute(
            select(func.count(PipelineRun.id)).where(PipelineRun.status == "FAILED")
        )).scalar() or 0
        cancelled_count = (await self.session.execute(
            select(func.count(PipelineRun.id)).where(PipelineRun.status == "CANCELLED")
        )).scalar() or 0

        # 3. Total Tasks (Step Executions)
        tasks_count = (await self.session.execute(select(func.count(StepExecution.id)))).scalar() or 0

        # 4. Average Duration
        avg_duration = (await self.session.execute(
            select(func.avg(PipelineRun.duration_seconds)).where(PipelineRun.duration_seconds.isnot(None))
        )).scalar() or 0.0

        # Success Rate
        completed_runs = success_count + failed_count + cancelled_count
        success_rate = round((success_count / completed_runs * 100.0), 2) if completed_runs > 0 else 0.0

        return StatsResponse(
            total_pipelines=pipelines_count,
            total_runs=runs_count,
            total_tasks=tasks_count,
            successful_runs=success_count,
            failed_runs=failed_count,
            cancelled_runs=cancelled_count,
            success_rate=success_rate,
            average_duration_seconds=round(float(avg_duration), 2),
        )
