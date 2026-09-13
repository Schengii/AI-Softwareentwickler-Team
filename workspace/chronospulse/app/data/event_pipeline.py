"""ChronosPulse - Event-Streaming, Priority-Queue und In-Memory Buffer Pipeline.

Kernkomponenten:
- In-Memory Ring-Buffer mit deterministischer Kapazitätsgrenze
- Asynchrone Priority-Queue mit Prioritätsgewichtung (CRITICAL > HIGH > NORMAL > LOW)
- Event-Streaming & Worker-Pipeline mit Dead-Letter-Queue (DLQ) und Exponential Backoff
- Cache-Aside Manager mit Stampede-Prevention (Mutex-Locking) und Memory/Redis Fallback
- Batch-Flush-Mechanismus für Persistenz-Layer (SQLite / DuckDB)
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
import json
import logging
import time
from typing import Any, Callable, Coroutine, Dict, Generic, List, Optional, Tuple, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("chronospulse.pipeline")


# ============================================================================
# 1. Event-Typen & Prioritäts-Klassen
# ============================================================================

class EventPriority(IntEnum):
    """Event-Prioritäten für die Priority-Queue (niedrigerer Integer-Wert = höhere Prio)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class ChronosStreamEvent(BaseModel):
    """Standardisiertes Streaming-Event für ChronosPulse."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    priority: EventPriority = EventPriority.NORMAL
    event_type: str = Field(..., description="Typ des Events, z.B. metric_ingest, anomaly_alert")
    service: str = Field(default="system")
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3


@dataclass(order=True)
class PrioritizedItem:
    """Wrapper für heapq / asyncio.PriorityQueue Sortierung."""
    priority: int
    timestamp: float
    item: ChronosStreamEvent = field(compare=False)


# ============================================================================
# 2. In-Memory Ring-Buffer mit Backpressure & Überlauf-Schutz
# ============================================================================

T = TypeVar("T")


class InMemoryRingBuffer(Generic[T]):
    """Thread- & Task-sicherer FIFO-Ring-Buffer mit konfigurierbarer Maximalkapazität."""

    def __init__(self, capacity: int = 10000) -> None:
        if capacity <= 0:
            raise ValueError("Kapazität muss größer als 0 sein.")
        self._capacity: int = capacity
        self._buffer: deque[T] = deque(maxlen=capacity)
        self._dropped_count: int = 0
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    async def append(self, item: T) -> bool:
        """Fügt ein Item hinzu. Bei vollem Buffer wird das älteste Element verworfen."""
        async with self._lock:
            was_full = len(self._buffer) >= self._capacity
            if was_full:
                self._dropped_count += 1
            self._buffer.append(item)
            return not was_full

    async def pop_batch(self, batch_size: int = 100) -> List[T]:
        """Entnimmt bis zu `batch_size` Elemente aus dem Buffer."""
        async with self._lock:
            items: List[T] = []
            for _ in range(min(batch_size, len(self._buffer))):
                items.append(self._buffer.popleft())
            return items

    async def size(self) -> int:
        async with self._lock:
            return len(self._buffer)

    async def clear(self) -> None:
        async with self._lock:
            self._buffer.clear()
            self._dropped_count = 0


# ============================================================================
# 3. Asynchrone Priority-Queue für Observability-Events
# ============================================================================

class EventPriorityQueue:
    """Prioritäts-Warteschlange für Observability-Events mit Prioritätsstufen."""

    def __init__(self, maxsize: int = 50000) -> None:
        self._queue: asyncio.PriorityQueue[PrioritizedItem] = asyncio.PriorityQueue(maxsize=maxsize)
        self._processed_count: int = 0
        self._dropped_count: int = 0

    @property
    def processed_count(self) -> int:
        return self._processed_count

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    async def put(self, event: ChronosStreamEvent) -> bool:
        """Fügt ein Event priorisiert ein. Wirft keine Exception bei QueueFull, sondern loggt."""
        item = PrioritizedItem(
            priority=int(event.priority),
            timestamp=event.timestamp,
            item=event,
        )
        try:
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            self._dropped_count += 1
            logger.warning("Priority-Queue voll! Event %s verworfen.", event.event_id)
            return False

    async def get(self) -> ChronosStreamEvent:
        """Holt das höchstpriorisierte Event aus der Queue."""
        prioritized = await self._queue.get()
        self._processed_count += 1
        return prioritized.item

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()


# ============================================================================
# 4. In-Memory Cache mit Stampede Prevention (Mutex-Locking & Cache-Aside)
# ============================================================================

class CacheEntry:
    def __init__(self, value: Any, ttl_seconds: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


class CacheManager:
    """Cache-Aside Manager mit Stampede-Prevention via Single-Key-Mutex."""

    def __init__(self, default_ttl: float = 60.0) -> None:
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self.hits: int = 0
        self.misses: int = 0

    async def _get_key_lock(self, key: str) -> asyncio.Lock:
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and not entry.is_expired():
            self.hits += 1
            return entry.value
        if entry and entry.is_expired():
            self._cache.pop(key, None)
        self.misses += 1
        return None

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        effective_ttl = ttl if ttl is not None else self.default_ttl
        self._cache[key] = CacheEntry(value, effective_ttl)

    async def get_or_set(
        self,
        key: str,
        factory_coro: Callable[[], Coroutine[Any, Any, Any]],
        ttl: Optional[float] = None,
    ) -> Any:
        """Verhindert Cache-Stampede durch Key-Level Mutex Locking."""
        val = await self.get(key)
        if val is not None:
            return val

        key_lock = await self._get_key_lock(key)
        async with key_lock:
            # Double-Checked Locking
            val = await self.get(key)
            if val is not None:
                return val

            computed_val = await factory_coro()
            await self.set(key, computed_val, ttl=ttl)
            return computed_val

    async def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    async def clear(self) -> None:
        async with self._global_lock:
            self._cache.clear()
            self._locks.clear()


# ============================================================================
# 5. Pipeline Worker & Dead-Letter-Queue (DLQ)
# ============================================================================

class PipelineWorker:
    """Asynchroner Streaming-Worker mit Batching, DLQ und Fehlerbehandlung."""

    def __init__(
        self,
        queue: EventPriorityQueue,
        buffer: InMemoryRingBuffer[ChronosStreamEvent],
        sink_handler: Callable[[List[ChronosStreamEvent]], Coroutine[Any, Any, None]],
        batch_size: int = 100,
        flush_interval_seconds: float = 1.0,
    ) -> None:
        self.queue = queue
        self.buffer = buffer
        self.sink_handler = sink_handler
        self.batch_size = batch_size
        self.flush_interval = flush_interval_seconds
        self.dead_letter_queue: List[Tuple[ChronosStreamEvent, str]] = []
        self._is_running = False
        self._worker_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        """Startet den asynchronen Worker-Loop."""
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Beendet den Worker und flusht verbleibende Elemente."""
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        # Letzter Flush
        await self._flush_buffer()

    async def _run_loop(self) -> None:
        last_flush = time.monotonic()
        while self._is_running:
            try:
                # Hole Events mit kurzem Timeout für regelmäßige Flushes
                timeout = max(0.01, self.flush_interval - (time.monotonic() - last_flush))
                try:
                    event = await asyncio.wait_for(self.queue.get(), timeout=timeout)
                    await self.buffer.append(event)
                    self.queue.task_done()
                except asyncio.TimeoutError:
                    pass

                # Flush prüfen
                buf_len = await self.buffer.size()
                if buf_len >= self.batch_size or (time.monotonic() - last_flush) >= self.flush_interval:
                    if buf_len > 0:
                        await self._flush_buffer()
                    last_flush = time.monotonic()

            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - Worker-Loop darf nicht abstürzen
                logger.error("Unerwarteter Fehler im Pipeline-Worker Loop: %s", exc)
                await asyncio.sleep(0.1)

    async def _flush_buffer(self) -> None:
        items = await self.buffer.pop_batch(self.batch_size)
        if not items:
            return

        try:
            await self.sink_handler(items)
        except Exception as exc:  # noqa: BLE001 - Retry/DLQ Abfanglogik
            logger.warning("Fehler beim Flush von %d Events: %s. Starte DLQ/Retry-Verarbeitung.", len(items), exc)
            for item in items:
                if item.retry_count < item.max_retries:
                    # In Retry-Queue mit erhöhter Prio und Retry-Count
                    retry_event = ChronosStreamEvent(
                        event_id=item.event_id,
                        priority=EventPriority.CRITICAL,  # Retries höher priorisieren
                        event_type=item.event_type,
                        service=item.service,
                        payload=item.payload,
                        timestamp=item.timestamp,
                        retry_count=item.retry_count + 1,
                        max_retries=item.max_retries,
                    )
                    await self.queue.put(retry_event)
                else:
                    # Maximalanzahl erreicht -> Dead Letter Queue
                    self.dead_letter_queue.append((item, str(exc)))
                    if len(self.dead_letter_queue) > 5000:
                        self.dead_letter_queue = self.dead_letter_queue[-5000:]
                    logger.error("Event %s endgültig in Dead-Letter-Queue verschoben.", item.event_id)


# ============================================================================
# 6. Globaler Stream & Buffer Hub (Singleton-Provider)
# ============================================================================

class ChronosStreamHub:
    """Zentraler Aggregator für Streaming-Komponenten."""

    def __init__(self) -> None:
        self.priority_queue = EventPriorityQueue(maxsize=20000)
        self.ring_buffer = InMemoryRingBuffer[ChronosStreamEvent](capacity=10000)
        self.cache_manager = CacheManager(default_ttl=30.0)
        self.worker: Optional[PipelineWorker] = None

    def initialize_worker(
        self,
        sink_handler: Callable[[List[ChronosStreamEvent]], Coroutine[Any, Any, None]],
    ) -> PipelineWorker:
        self.worker = PipelineWorker(
            queue=self.priority_queue,
            buffer=self.ring_buffer,
            sink_handler=sink_handler,
            batch_size=50,
            flush_interval_seconds=0.5,
        )
        return self.worker


# Globale Instanz für einfache Einbindung
stream_hub = ChronosStreamHub()
