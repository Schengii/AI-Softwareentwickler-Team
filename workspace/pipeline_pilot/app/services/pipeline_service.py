
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Pipeline, PipelineRun
from app.schemas import PipelineCreate, PipelineUpdate


class PipelineService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_pipelines(self) -> list[Pipeline]:
        stmt = select(Pipeline).order_by(Pipeline.id.desc())
        result = await self.session.execute(stmt)
        pipelines = list(result.scalars().all())

        # Für jede Pipeline den Status des letzten Runs ermitteln
        for p in pipelines:
            run_stmt = (
                select(PipelineRun.status)
                .where(PipelineRun.pipeline_id == p.id)
                .order_by(PipelineRun.id.desc())
                .limit(1)
            )
            run_res = await self.session.execute(run_stmt)
            p.last_run_status = run_res.scalar_one_or_none()

        return pipelines

    async def get_pipeline(self, pipeline_id: int) -> Pipeline | None:
        stmt = select(Pipeline).where(Pipeline.id == pipeline_id)
        result = await self.session.execute(stmt)
        pipeline = result.scalar_one_or_none()
        if pipeline:
            run_stmt = (
                select(PipelineRun.status)
                .where(PipelineRun.pipeline_id == pipeline.id)
                .order_by(PipelineRun.id.desc())
                .limit(1)
            )
            run_res = await self.session.execute(run_stmt)
            pipeline.last_run_status = run_res.scalar_one_or_none()
        return pipeline

    async def create_pipeline(self, pipeline_in: PipelineCreate) -> Pipeline:
        steps_dicts = [s.model_dump() for s in pipeline_in.steps]
        pipeline = Pipeline(
            name=pipeline_in.name,
            description=pipeline_in.description,
            trigger_type=pipeline_in.trigger_type,
            steps=steps_dicts,
        )
        self.session.add(pipeline)
        await self.session.commit()
        await self.session.refresh(pipeline)
        pipeline.last_run_status = None
        return pipeline

    async def update_pipeline(self, pipeline_id: int, pipeline_in: PipelineUpdate) -> Pipeline | None:
        pipeline = await self.get_pipeline(pipeline_id)
        if not pipeline:
            return None

        if pipeline_in.name is not None:
            pipeline.name = pipeline_in.name
        if pipeline_in.description is not None:
            pipeline.description = pipeline_in.description
        if pipeline_in.trigger_type is not None:
            pipeline.trigger_type = pipeline_in.trigger_type
        if pipeline_in.steps is not None:
            pipeline.steps = [s.model_dump() for s in pipeline_in.steps]

        await self.session.commit()
        await self.session.refresh(pipeline)
        return pipeline

    async def delete_pipeline(self, pipeline_id: int) -> bool:
        stmt = delete(Pipeline).where(Pipeline.id == pipeline_id)
        res = await self.session.execute(stmt)
        await self.session.commit()
        return (res.rowcount or 0) > 0
