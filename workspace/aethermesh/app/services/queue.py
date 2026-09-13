"""AetherMesh Engine - Queue Management & Spooling.

Verwaltet die In-Memory Priority-Queue mit persistenter SQLite-Absicherung
und Backpressure-Integration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from sqlalchemy import select, update
from app.db.session import async_session_factory
from app.db.models import JobModel, JobStatus
from app.services.backpressure import BackpressureController

logger = logging.getLogger(__name__)


class JobQueueManager:
    """Orchestrierungs-Manager für Priority-Queue und SQLite-Persistenz."""

    def __init__(self, backpressure_controller: Optional[BackpressureController] = None, max_size: int = 1000):
        self._queue: asyncio.PriorityQueue[tuple[int, float, dict[str, Any]]] = asyncio.PriorityQueue(maxsize=max_size)
        self.backpressure_controller = backpressure_controller or BackpressureController()
        self.max_size = max_size

    @property
    def qsize(self) -> int:
        """Liefert die aktuelle Anzahl an Elementen in der In-Memory-Queue."""
        return self._queue.qsize()

    async def enqueue(self, job_data: dict[str, Any], priority: int = 10) -> bool:
        """Fügt einen Job unter Berücksichtigung von Backpressure in die Queue ein."""
        admitted, _ = self.backpressure_controller.check_admission()
        if not admitted:
            logger.warning("Backpressure aktiv - Job %s abgewiesen", job_data.get("id"))
            return False

        # In SQLite persistieren falls async_session_factory bereitsteht
        try:
            async with async_session_factory() as session:
                job_id = job_data.get("id")
                stmt = select(JobModel).where(JobModel.id == job_id)
                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()
                if not existing and job_id:
                    new_job = JobModel(
                        id=job_id,
                        payload=job_data.get("payload", {}),
                        priority=priority,
                        status=JobStatus.PENDING,
                    )
                    session.add(new_job)
                    await session.commit()
        except Exception as err:
            logger.error("Fehler beim SQLite-Spooling von Job %s: %s", job_data.get("id"), err)

        # In In-Memory PriorityQueue legen
        import time
        await self._queue.put((priority, time.time(), job_data))
        self.backpressure_controller.update_metrics(queue_depth=self._queue.qsize())
        return True

    async def dequeue(self) -> tuple[int, float, dict[str, Any]]:
        """Entnimmt den nächsten Job mit höchster Priorität (kleinster Integer)."""
        item = await self._queue.get()
        self.backpressure_controller.update_metrics(queue_depth=self._queue.qsize())
        return item

    def task_done(self) -> None:
        """Markiert einen Task als abgearbeitet in der PriorityQueue."""
        self._queue.task_done()

    async def recover_pending_jobs(self) -> int:
        """Lädt beim Startup unfertige Jobs aus SQLite zurück in die In-Memory-Queue."""
        recovered = 0
        try:
            async with async_session_factory() as session:
                stmt = select(JobModel).where(JobModel.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]))
                result = await session.execute(stmt)
                jobs = result.scalars().all()

                import time
                for job in jobs:
                    job_data = {
                        "id": job.id,
                        "payload": job.payload,
                        "priority": job.priority,
                        "retries": job.retries,
                    }
                    await self._queue.put((job.priority, time.time(), job_data))
                    recovered += 1

                logger.info("%d unfertige Jobs aus SQLite wiederhergestellt", recovered)
        except Exception as err:
            logger.error("Fehler beim Recovery aus SQLite: %s", err)

        return recovered
