import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    payload: dict[str, Any]
    timestamp: float = Field(default_factory=time.monotonic)
    retries: int = 0

class DeadLetterEvent(BaseModel):
    event: Event
    error_reason: str
    failed_at: float = Field(default_factory=time.monotonic)

class EventBus:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._subscribers: dict[str, list[Callable[[Event], Coroutine[Any, Any, None]]]] = {}
        self._dlq: list[DeadLetterEvent] = []
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    def subscribe(self, event_type: str, handler: Callable[[Event], Coroutine[Any, Any, None]]) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        await self._queue.put(event)

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def _worker(self) -> None:
        while True:
            try:
                event = await self._queue.get()
                handlers = self._subscribers.get(event.type, [])
                
                if not handlers:
                    self._queue.task_done()
                    continue

                success = True
                error_msg = ""
                for handler in handlers:
                    try:
                        await handler(event)
                    except Exception as e:
                        logger.error(f"Handler failed for event {event.id}: {e}")
                        success = False
                        error_msg = str(e)
                        break
                
                if not success:
                    if event.retries < self.max_retries:
                        event.retries += 1
                        # Simple backoff
                        await asyncio.sleep(2 ** event.retries)
                        await self._queue.put(event)
                    else:
                        self._dlq.append(DeadLetterEvent(event=event, error_reason=error_msg))
                
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e: # noqa: BLE001 - Worker darf nie abstürzen
                logger.error(f"Event bus worker error: {e}")

    def get_dlq(self) -> list[DeadLetterEvent]:
        return self._dlq

event_bus = EventBus()
