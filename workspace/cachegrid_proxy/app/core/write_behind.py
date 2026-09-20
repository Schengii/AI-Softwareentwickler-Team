"""Write-Behind Verarbeitungs-Queue zur asynchronen Festplatten-Persistierung."""

import asyncio
import logging
from typing import Any

from app.core.disk_storage import DiskTierStorage
from app.core.lru_cache import CacheEntry

logger = logging.getLogger("cachegrid.write_behind")


class WriteBehindWorker:
    """Asynchroner Hintergrund-Worker für Write-Behind Disk-Persistierung."""

    def __init__(
        self,
        disk_storage: DiskTierStorage,
        flush_interval: float = 0.5,
        batch_size: int = 50,
    ) -> None:
        self.disk_storage = disk_storage
        self.flush_interval = flush_interval
        self.batch_size = batch_size
        self._queue: asyncio.Queue[CacheEntry] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running: bool = False
        self._total_flushed: int = 0
        self._flush_lock = asyncio.Lock()

    def start(self) -> None:
        """Startet den Write-Behind Worker-Task."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._worker_loop())
            logger.info("Write-Behind Worker erfolgreich gestartet.")

    async def enqueue(self, entry: CacheEntry) -> None:
        """Fügt einen Eintrag in die Schreibwarteschlange ein."""
        await self._queue.put(entry)

    async def _worker_loop(self) -> None:
        """Dauerhafter Loop, der die Queue periodisch abarbeitet."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - Worker-Loop darf nicht abstürzen
                logger.error("Unerwarteter Fehler im Write-Behind Worker: %s", exc)

    async def flush(self) -> int:
        """Flusht alle aktuell in der Queue befindlichen Einträge auf Disk."""
        async with self._flush_lock:
            batch: list[CacheEntry] = []
            while not self._queue.empty() and len(batch) < self.batch_size:
                try:
                    entry = self._queue.get_nowait()
                    batch.append(entry)
                    self._queue.task_done()
                except asyncio.QueueEmpty:
                    break

            if batch:
                await self.disk_storage.save_batch(batch)
                self._total_flushed += len(batch)
                logger.debug("%d Einträge im Write-Behind Batch geflusht.", len(batch))
            return len(batch)

    async def stop(self) -> None:
        """Stoppt den Worker und flusht alle verbleibenden Elemente."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Restliche Elemente leeren und flushen
        while not self._queue.empty():
            await self.flush()
        logger.info("Write-Behind Worker beendet.")

    def get_stats(self) -> dict[str, Any]:
        """Liefert Metriken zum Write-Behind Zustand."""
        return {
            "queue_size": self._queue.qsize(),
            "total_flushed": self._total_flushed,
            "running": self._running,
        }
