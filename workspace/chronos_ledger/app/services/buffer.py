"""Buffer-Service zur asynchronen Hintergrundverarbeitung und Batch-Flushing."""
from __future__ import annotations

import asyncio
import logging

from app.services.ledger_service import ledger_service
from app.services.ring_buffer import ring_buffer

logger = logging.getLogger(__name__)


class RingBufferService:
    """Hintergrund-Worker für asynchrones Batch-Flushing aus dem Ring-Buffer."""

    def __init__(self):
        self._worker_task: asyncio.Task | None = None
        self._running: bool = False

    async def start(self) -> None:
        """Startet den Hintergrund-Worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("RingBufferService Hintergrund-Worker gestartet.")

    async def stop(self) -> None:
        """Beendet den Worker und leert den verbleibenden Puffer (Drain)."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        # Restliche Elemente im Buffer leeren (Graceful Drain)
        await self._flush_all()
        logger.info("RingBufferService gestoppt und Puffer geleert.")

    async def _flush_all(self) -> None:
        """Schreibt alle verbliebenen Einträge im Puffer in den Ledger."""
        while not ring_buffer.is_empty():
            batch = await ring_buffer.get_batch(max_batch_size=500, timeout=0.01)
            if not batch:
                break
            for item in batch:
                tenant_id = item.get("tenant_id", "default")
                payload = item.get("payload", {})
                ledger_service.append(tenant_id, payload)

    async def _worker_loop(self) -> None:
        """Hintergrundschleife für periodisches Batch-Flushing."""
        while self._running:
            try:
                batch = await ring_buffer.get_batch(max_batch_size=100, timeout=0.2)
                if batch:
                    for item in batch:
                        tenant_id = item.get("tenant_id", "default")
                        payload = item.get("payload", {})
                        ledger_service.append(tenant_id, payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - Worker-Schleife darf bei Einzelfehlern nicht abbrechen
                logger.error("Fehler im RingBuffer Worker-Loop: %s", exc)
                await asyncio.sleep(0.1)


ring_buffer_service = RingBufferService()
