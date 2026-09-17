import asyncio
import logging
from typing import Any

from app.schemas.metric import BroadcastEvent

logger = logging.getLogger(__name__)


class EventBus:
    """In-Memory Pub/Sub Event Bus für WebSocket-Clients und interne Entkopplung.
    
    Verwendet asyncio.Queue pro Subscriber. Keine Event-Loop-Erzeugung im __init__.
    """

    def __init__(self, default_queue_size: int = 1000) -> None:
        self._default_queue_size = default_queue_size
        self._subscribers: set[asyncio.Queue] = set()
        self._channel_subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def subscribe(self, channel: str | None = None, maxsize: int | None = None) -> asyncio.Queue:
        """Registriert einen neuen Subscriber und gibt dessen Queue zurück."""
        q_size = maxsize or self._default_queue_size
        queue: asyncio.Queue = asyncio.Queue(maxsize=q_size)

        lock = self._get_lock()
        async with lock:
            if channel:
                if channel not in self._channel_subscribers:
                    self._channel_subscribers[channel] = set()
                self._channel_subscribers[channel].add(queue)
            else:
                self._subscribers.add(queue)

        logger.debug("Subscriber registriert (channel=%s, total=%d)", channel, self.subscriber_count(channel))
        return queue

    async def unsubscribe(self, queue: asyncio.Queue, channel: str | None = None) -> None:
        """Entfernt einen Subscriber."""
        lock = self._get_lock()
        async with lock:
            if channel and channel in self._channel_subscribers:
                self._channel_subscribers[channel].discard(queue)
                if not self._channel_subscribers[channel]:
                    del self._channel_subscribers[channel]
            else:
                self._subscribers.discard(queue)

        logger.debug("Subscriber entfernt (channel=%s)", channel)

    async def publish(self, event: Any, channel: str | None = None) -> int:
        """Verteilt ein Event an alle registrierten Queues (Broadcast).
        
        Gibt die Anzahl der erfolgreich benachrichtigten Subscriber zurück.
        Langsame Subscriber werden bei voller Queue nicht blockiert (Drop + Warning).
        """
        payload = event.model_dump() if isinstance(event, BroadcastEvent) else event

        lock = self._get_lock()
        async with lock:
            if channel:
                targets = list(self._channel_subscribers.get(channel, set()))
            else:
                targets = list(self._subscribers)

        delivered = 0
        for queue in targets:
            try:
                queue.put_nowait(payload)
                delivered += 1
            except asyncio.QueueFull:
                # Slow-Consumer-Protection: Verhindert Memory-Explosion und Latenz-Spikes
                logger.warning("Subscriber-Queue voll. Älteste Nachricht verworfen / Nachricht gedroppt.")
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                    delivered += 1
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
        return delivered

    def subscriber_count(self, channel: str | None = None) -> int:
        """Gibt die aktuelle Anzahl der aktiven Subscriber zurück."""
        if channel:
            return len(self._channel_subscribers.get(channel, set()))
        return len(self._subscribers)

    async def clear(self) -> None:
        """Löscht alle aktiven Subscriptions."""
        lock = self._get_lock()
        async with lock:
            self._subscribers.clear()
            self._channel_subscribers.clear()


_default_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Factory-Accessor für den globalen EventBus (Lazy Singleton ohne Modulevel-Loop-Aufruf)."""
    global _default_event_bus
    if _default_event_bus is None:
        _default_event_bus = EventBus()
    return _default_event_bus
