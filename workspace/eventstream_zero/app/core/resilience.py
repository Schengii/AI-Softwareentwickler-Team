"""Resilience, Circuit Breaker, Retry Policy und Dead-Letter-Queue (DLQ) für EventStream-Zero.

Produktionsreife Implementierung gemäß Site Reliability & Chaos Engineering Best Practices:
- Circuit Breaker mit CLOSED, OPEN, HALF_OPEN Zuständen via time.monotonic()
- Exponentielles Backoff mit Jitter (Bandit-konform via secrets.SystemRandom)
- Dead-Letter-Queue (DLQ) mit DeadLetterMessage-Tracking
- Chaos-Simulator für Consumer-Crashes, Latenzinjektion und Sink-Ausfälle
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Zustände des Circuit Breakers."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Wird ausgelöst, wenn ein Call an einen geöffneten Circuit Breaker gerichtet wird."""


@dataclass
class RetryPolicy:
    """Konfiguration für exponentielles Backoff mit Jitter."""
    max_retries: int = 3
    initial_delay: float = 0.1
    max_delay: float = 2.0
    backoff_factor: float = 2.0
    jitter: bool = True

    def calculate_delay(self, attempt: int) -> float:
        """Berechnet die Verzögerung für den n-ten Retry-Versuch mit Jitter."""
        raw_delay = self.initial_delay * (self.backoff_factor ** attempt)
        delay = min(raw_delay, self.max_delay)
        if self.jitter:
            # Bandit-konformer Zufallsgenerator für Jitter (Full Jitter)
            rng = secrets.SystemRandom()
            delay = rng.uniform(0.0, delay)
        return delay


class CircuitBreaker:
    """Asynchroner Circuit Breaker für externe Sinks und abhängige Services.
    
    Verwendet time.monotonic() für zuverlässige Zeitmessung ohne Event-Loop-Bindung.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 10.0,
        success_threshold: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_state_change = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Gibt den aktuellen Circuit-Zustand zurück unter Berücksichtigung von Timeouts."""
        if self._state == CircuitState.OPEN:
            now = time.monotonic()
            if now - self._last_state_change >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                self._last_state_change = now
        return self._state

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: Callable[..., Awaitable[T]] | None = None,
        **kwargs: Any,
    ) -> T:
        """Führt eine asynchrone Funktion geschützt durch den Circuit Breaker aus."""
        async with self._lock:
            current_state = self.state

            if current_state == CircuitState.OPEN:
                logger.warning(
                    "Circuit Breaker '%s' ist OPEN. Call wird abgewiesen.", self.name
                )
                if fallback is not None:
                    return await fallback(*args, **kwargs)
                raise CircuitBreakerOpenError(
                    f"Circuit Breaker '{self.name}' ist OPEN (Recovery nach {self.recovery_timeout}s)."
                )

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as exc:
            await self._on_failure(exc)
            if fallback is not None:
                logger.info("Circuit Breaker '%s' nutzt Fallback nach Fehler: %s", self.name, exc)
                return await fallback(*args, **kwargs)
            raise

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._last_state_change = time.monotonic()
                    logger.info("Circuit Breaker '%s' ist wieder CLOSED.", self.name)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    async def _on_failure(self, exc: Exception) -> None:
        async with self._lock:
            self._failure_count += 1
            now = time.monotonic()
            logger.warning(
                "Fehler in Circuit Breaker '%s' (%d/%d): %s",
                self.name,
                self._failure_count,
                self.failure_threshold,
                exc,
            )
            if self._state in (CircuitState.HALF_OPEN, CircuitState.CLOSED):
                if self._failure_count >= self.failure_threshold or self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.OPEN
                    self._last_state_change = now
                    logger.error("Circuit Breaker '%s' wechselt in Zustand OPEN!", self.name)


@dataclass
class DeadLetterMessage:
    """Eintrag in der Dead-Letter-Queue."""
    message_id: str
    topic: str
    payload: Any
    partition: int
    offset: int
    error_reason: str
    retry_count: int
    failed_at: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)


class DeadLetterQueue:
    """Verwaltet fehlgeschlagene Nachrichten zur manuellen Inspektion oder späteren Neuverarbeitung."""

    def __init__(self, max_size: int = 10000) -> None:
        self.max_size = max_size
        self._messages: list[DeadLetterMessage] = []
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        message_id: str,
        topic: str,
        payload: Any,
        partition: int,
        offset: int,
        error_reason: str,
        retry_count: int,
        metadata: dict[str, Any] | None = None,
    ) -> DeadLetterMessage:
        """Fügt eine Nachricht der DLQ hinzu."""
        dlq_msg = DeadLetterMessage(
            message_id=message_id,
            topic=topic,
            payload=payload,
            partition=partition,
            offset=offset,
            error_reason=error_reason,
            retry_count=retry_count,
            failed_at=time.monotonic(),
            metadata=metadata or {},
        )
        async with self._lock:
            if len(self._messages) >= self.max_size:
                # FIFO Verdrängung bei DLQ-Überlauf
                self._messages.pop(0)
            self._messages.append(dlq_msg)
            logger.error(
                "Nachricht %s (Topic: %s, Partition: %d, Offset: %d) nach %d Retries an DLQ übergeben: %s",
                message_id,
                topic,
                partition,
                offset,
                retry_count,
                error_reason,
            )
        return dlq_msg

    async def get_messages(self, limit: int = 100) -> list[DeadLetterMessage]:
        """Gibt die gespeicherten DLQ-Nachrichten zurück."""
        async with self._lock:
            return list(self._messages[:limit])

    async def size(self) -> int:
        """Gibt die Anzahl der Nachrichten in der DLQ zurück."""
        async with self._lock:
            return len(self._messages)

    async def clear(self) -> None:
        """Leert die Dead-Letter-Queue."""
        async with self._lock:
            self._messages.clear()


class ResilientProcessor:
    """Führt Verarbeitungsoperationen mit Retries, Circuit Breaker und DLQ-Fallback aus."""

    def __init__(
        self,
        circuit_breaker: CircuitBreaker,
        dlq: DeadLetterQueue,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.circuit_breaker = circuit_breaker
        self.dlq = dlq
        self.retry_policy = retry_policy or RetryPolicy()

    async def process_with_resilience(
        self,
        func: Callable[..., Awaitable[T]],
        message_id: str,
        topic: str,
        payload: Any,
        partition: int = 0,
        offset: int = 0,
        *args: Any,
        **kwargs: Any,
    ) -> T | None:
        """Führt die Funktion mit Retries und Circuit Breaker aus; schickt bei Totalausfall an DLQ."""
        attempt = 0
        last_exception: Exception | None = None

        while attempt <= self.retry_policy.max_retries:
            try:
                return await self.circuit_breaker.call(func, *args, **kwargs)
            except Exception as exc:
                last_exception = exc
                if attempt < self.retry_policy.max_retries:
                    delay = self.retry_policy.calculate_delay(attempt)
                    logger.warning(
                        "Versuch %d für Msg %s fehlgeschlagen (%s). Retry in %.3fs...",
                        attempt + 1,
                        message_id,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                attempt += 1

        # Alle Retries erschöpft -> Dead-Letter-Queue
        await self.dlq.enqueue(
            message_id=message_id,
            topic=topic,
            payload=payload,
            partition=partition,
            offset=offset,
            error_reason=str(last_exception) if last_exception else "Unbekannter Fehler",
            retry_count=attempt - 1,
        )
        return None


class ChaosSimulator:
    """Chaos-Engineering-Tools zur Simulation von Ausfällen (Consumer Crashes, Latenz, Sinks)."""

    def __init__(self, failure_probability: float = 0.0, latency_spike_sec: float = 0.0) -> None:
        self.failure_probability = failure_probability
        self.latency_spike_sec = latency_spike_sec
        self.active = False
        self._crashed_consumers: set[str] = set()

    def enable(self) -> None:
        """Aktiviert Chaos-Injektion."""
        self.active = True

    def disable(self) -> None:
        """Deaktiviert Chaos-Injektion."""
        self.active = False
        self._crashed_consumers.clear()

    def simulate_consumer_crash(self, consumer_id: str) -> None:
        """Markiert einen Consumer explizit als abgestürzt."""
        self._crashed_consumers.add(consumer_id)
        logger.warning("[Chaos] Consumer '%s' wurde gezielt zum Absturz gebracht!", consumer_id)

    def is_consumer_crashed(self, consumer_id: str) -> bool:
        """Prüft, ob der Consumer im Crash-Status ist."""
        return consumer_id in self._crashed_consumers

    def recover_consumer(self, consumer_id: str) -> None:
        """Stellt einen zuvor abgestürzten Consumer wieder her."""
        self._crashed_consumers.discard(consumer_id)
        logger.info("[Chaos] Consumer '%s' wurde wiederhergestellt.", consumer_id)

    async def maybe_inject_fault(self, consumer_id: str | None = None) -> None:
        """Injiziert zufällige Ausfälle oder Latenzen, sofern aktiviert."""
        if not self.active:
            return

        if consumer_id and self.is_consumer_crashed(consumer_id):
            raise RuntimeError(f"[Chaos] Consumer {consumer_id} ist im abgestürzten Zustand.")

        rng = secrets.SystemRandom()
        if self.latency_spike_sec > 0:
            spike = rng.uniform(0.0, self.latency_spike_sec)
            logger.debug("[Chaos] Injiziere Latenz-Spike: %.3fs", spike)
            await asyncio.sleep(spike)

        if self.failure_probability > 0 and rng.random() < self.failure_probability:
            logger.warning("[Chaos] Injiziere simulierten Ausfall!")
            raise ConnectionResetError("[Chaos] Simulierter Netzwerk- oder Sink-Verbindungsabbruch.")
