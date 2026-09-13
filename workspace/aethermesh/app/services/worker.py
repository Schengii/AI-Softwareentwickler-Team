"""AetherMesh Engine - Worker Pool Service.

Verwaltet asynchrone Worker-Tasks zur Abarbeitung von Jobs aus der Priority Queue
mit exponentiellem Backoff, Dead-Letter-Queue (DLQ) Routing und Entlastung
des Event-Loops bei CPU-intensiven Analyse-Aufgaben.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.services.backpressure import BackpressureController
    from app.services.metrics import MetricsAggregator
    from app.services.queue import JobQueueManager

logger = logging.getLogger(__name__)


class WorkerPool:
    """Asynchroner Worker-Pool für Hintergrundjobs mit Fehlertoleranz."""

    def __init__(
        self,
        queue_manager: Optional[JobQueueManager] = None,
        metrics_aggregator: Optional[MetricsAggregator] = None,
        backpressure_controller: Optional[BackpressureController] = None,
        worker_count: Optional[int] = None,
    ) -> None:
        self.queue_manager = queue_manager
        self.metrics_aggregator = metrics_aggregator
        self.backpressure_controller = backpressure_controller
        self.settings = get_settings()
        self.worker_count = worker_count or getattr(self.settings, "WORKER_CONCURRENCY", 4)
        self._tasks: list[asyncio.Task[None]] = []
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Gibt an, ob der Worker-Pool aktiv läuft."""
        return self._is_running

    async def start(self) -> None:
        """Startet die konfigurierten Worker-Hintergrund-Tasks."""
        if self._is_running:
            return

        self._is_running = True
        logger.info("Starte WorkerPool mit %d Workern...", self.worker_count)
        for i in range(self.worker_count):
            task = asyncio.create_task(self._worker_loop(worker_id=i), name=f"worker-{i}")
            self._tasks.append(task)

    async def stop(self) -> None:
        """Stoppt alle Worker-Tasks graceful."""
        if not self._is_running:
            return

        logger.info("Stoppe WorkerPool graceful...")
        self._is_running = False
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

    async def _worker_loop(self, worker_id: int) -> None:
        """Hauptschleife eines einzelnen Workers."""
        logger.debug("Worker %d gestartet.", worker_id)
        while self._is_running:
            try:
                if self.queue_manager is None:
                    await asyncio.sleep(0.5)
                    continue

                job = await self.queue_manager.get_job()
                if job is None:
                    await asyncio.sleep(0.1)
                    continue

                await self._process_job_safe(job)

            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - Worker-Loop darf bei unerwartetem Fehler nicht sterben
                logger.error("Unerwarteter Fehler im Worker %d: %s", worker_id, exc)
                await asyncio.sleep(0.5)

    async def _process_job_safe(self, job: Any) -> None:
        """Verarbeitet einen Job sicher mit Retry-Logik und DLQ-Routing."""
        job_id = getattr(job, "id", None) or (job.get("id") if isinstance(job, dict) else str(job))
        attempts = getattr(job, "attempts", 0) if not isinstance(job, dict) else job.get("attempts", 0)

        try:
            await self._update_job_status(job_id, "processing")
            # Führe Job-Abarbeitung aus
            await self.process_job(job)
            await self._update_job_status(job_id, "completed")
            if self.metrics_aggregator and hasattr(self.metrics_aggregator, "record_job_success"):
                await self.metrics_aggregator.record_job_success(job_id)

        except Exception as exc:  # noqa: BLE001 - Job-Fehlerbehandlung für Retry/DLQ
            logger.warning("Fehler bei Verarbeitung von Job %s: %s", job_id, exc)
            max_retries = getattr(self.settings, "MAX_RETRIES", 3)
            base_delay = getattr(self.settings, "BASE_RETRY_DELAY_SEC", 1.0)
            backoff_factor = getattr(self.settings, "RETRY_BACKOFF_FACTOR", 2.0)

            if attempts < max_retries:
                delay = base_delay * (backoff_factor ** attempts)
                if isinstance(job, dict):
                    job["attempts"] = attempts + 1
                elif hasattr(job, "attempts"):
                    job.attempts = attempts + 1
                asyncio.create_task(self._delayed_requeue(job, delay))
            else:
                # Dead-Letter-Queue (DLQ) Quarantäne
                await self._update_job_status(job_id, "dlq")
                if self.metrics_aggregator and hasattr(self.metrics_aggregator, "record_job_dlq"):
                    await self.metrics_aggregator.record_job_dlq(job_id)

    async def process_job(self, job: Any) -> Any:
        """Führt die fachliche Logik eines Jobs aus."""
        # Kann durch Subklassen oder ML-Analyzer überschrieben bzw. ergänzt werden
        data = job.get("data") if isinstance(job, dict) else getattr(job, "data", None)
        return data

    async def _delayed_requeue(self, job_data: Any, delay: float) -> None:
        """Stellt einen fehlgeschlagenen Job nach einer Verzögerung wieder in die Queue."""
        await asyncio.sleep(delay)
        if self.queue_manager and hasattr(self.queue_manager, "enqueue_job"):
            await self.queue_manager.enqueue_job(job_data)

    async def _update_job_status(self, job_id: Any, status: str) -> None:
        """Aktualisiert den Status eines Jobs im Queue-Manager oder DB-Layer."""
        if self.queue_manager and hasattr(self.queue_manager, "update_status"):
            await self.queue_manager.update_status(job_id, status)
