from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[Project]:
        result = await self.session.execute(select(Project))
        return list(result.scalars().all())

    async def get_by_id(self, project_id: int) -> Project | None:
        result = await self.session.execute(select(Project).where(Project.id == project_id))
        return result.scalars().first()

    async def create(self, name: str, description: str | None = None) -> Project:
        project = Project(name=name, description=description)
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def update(self, project_id: int, name: str | None = None, description: str | None = None) -> Project | None:
        project = await self.get_by_id(project_id)
        if not project:
            return None
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def delete(self, project_id: int) -> bool:
        project = await self.get_by_id(project_id)
        if not project:
            return False
        await self.session.delete(project)
        await self.session.commit()
        return True
