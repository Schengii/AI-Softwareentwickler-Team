"""In-Memory Ring-Buffer Queue für hochperformanten Audit-Log-Ingest."""
from __future__ import annotations

import asyncio
from typing import Any


class RingBufferQueue:
    """Asynchrone Queue / Ring-Buffer mit Kapazitätsgrenze und Batch-Drain."""

    def __init__(self, capacity: int = 10000):
        self.capacity = capacity
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=capacity)

    async def put(self, item: dict[str, Any]) -> bool:
        """Fügt ein Item in den Puffer ein. Gibt False zurück bei vollem Puffer."""
        try:
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            return False

    async def get_batch(self, max_batch_size: int = 100, timeout: float = 0.5) -> list[dict[str, Any]]:
        """Liest bis zu max_batch_size Einträge aus dem Puffer."""
        batch: list[dict[str, Any]] = []
        try:
            first_item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            batch.append(first_item)
            self._queue.task_done()
        except asyncio.TimeoutError:
            return batch

        while len(batch) < max_batch_size:
            try:
                item = self._queue.get_nowait()
                batch.append(item)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        return batch

    def qsize(self) -> int:
        return self._queue.qsize()

    def is_empty(self) -> bool:
        return self._queue.empty()


ring_buffer = RingBufferQueue()
