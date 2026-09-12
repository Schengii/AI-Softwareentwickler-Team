"""OmniQueue Resilience Engine
Implementiert Circuit-Breaker, Exponential-Backoff mit Jitter und Ring-Buffer-Prioritätsqueue.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

import httpx


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Ausgelöst, wenn ein Aufruf blockiert wird, da der Circuit Breaker OPEN ist."""

    def __init__(self, target_url: str, retry_after: float):
        self.target_url = target_url
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker für '{target_url}' ist OPEN. Retry möglich in {retry_after:.2f}s"
        )


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    half_open_success_threshold: int = 2
    monitor_window_seconds: float = 60.0


class CircuitBreaker:
    def __init__(self, target_url: str, config: CircuitBreakerConfig | None = None):
        self.target_url = target_url
        self.config = config or CircuitBreakerConfig()
        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.success_count: int = 0
        self.last_state_change: float = time.monotonic()
        self.last_failure_time: float = 0.0
        self._lock = asyncio.Lock()

    async def can_execute(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            if self.state == CircuitState.OPEN:
                if now - self.last_state_change >= self.config.recovery_timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.last_state_change = now
                    self.success_count = 0
                    return True
                return False
            return True

    async def record_success(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.half_open_success_threshold:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    self.last_state_change = now
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    async def record_failure(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self.last_failure_time = now
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.last_state_change = now
                self.success_count = 0
            elif self.state == CircuitState.CLOSED:
                self.failure_count += 1
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
                    self.last_state_change = now

    def get_status(self) -> dict[str, Any]:
        now = time.monotonic()
        time_until_retry = max(
            0.0,
            self.config.recovery_timeout_seconds - (now - self.last_state_change),
        ) if self.state == CircuitState.OPEN else 0.0

        return {
            "target_url": self.target_url,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "time_until_retry_seconds": round(time_until_retry, 2),
        }


@dataclass
class BackoffConfig:
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    factor: float = 2.0
    jitter: bool = True
    max_retries: int = 5


def calculate_backoff(attempt: int, config: BackoffConfig) -> float:
    """Berechnet exponentielles Backoff mit Full-Jitter nach AWS-Empfehlung."""
    if attempt <= 0:
        return 0.0
    calculated_delay = config.base_delay_seconds * (config.factor ** (attempt - 1))
    delay = min(config.max_delay_seconds, calculated_delay)
    if config.jitter:
        return random.uniform(0.0, delay)
    return delay


T = TypeVar("T")


class PriorityLevel(int, Enum):
    P1 = 1  # Höchste Priorität (Critical / Urgent)
    P2 = 2  # Mittlere Priorität (Normal)
    P3 = 3  # Niedrige Priorität (Bulk / Batch)


@dataclass(order=True)
class PrioritizedItem(Generic[T]):
    priority: int
    timestamp: float = field(compare=True)
    item_id: str = field(compare=False)
    data: T = field(compare=False)


class QueueOverflowPolicy(str, Enum):
    DROP_LOWEST = "drop_lowest"
    REJECT = "reject"


class RingBufferPriorityQueue(Generic[T]):
    """
    Kombinierter Ring-Buffer mit Prioritätsunterstützung (P1 > P2 > P3).
    Verhindert Out-of-Memory durch feste Obergrenze und deterministisches Drop-Verhalten.
    """

    def __init__(self, capacity: int = 1000, overflow_policy: QueueOverflowPolicy = QueueOverflowPolicy.DROP_LOWEST):
        if capacity <= 0:
            raise ValueError("Kapazität muss positiv sein.")
        self.capacity = capacity
        self.overflow_policy = overflow_policy
        self._queue: list[PrioritizedItem[T]] = []
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Condition(self._lock)
        self.dropped_count: int = 0
        self.total_enqueued: int = 0

    async def put(self, item_id: str, priority: PriorityLevel, data: T) -> bool:
        async with self._not_empty:
            element = PrioritizedItem(
                priority=priority.value,
                timestamp=time.time(),
                item_id=item_id,
                data=data,
            )

            if len(self._queue) >= self.capacity:
                if self.overflow_policy == QueueOverflowPolicy.REJECT:
                    return False

                # DROP_LOWEST: Prüfen, ob wir ein Element mit niedrigerer oder gleicher Priorität verdrängen können
                # Suche das Element mit höchstem Prioritätswert (P3 > P2 > P1)
                highest_prio_idx = max(range(len(self._queue)), key=lambda idx: (self._queue[idx].priority, self._queue[idx].timestamp))
                if self._queue[highest_prio_idx].priority >= priority.value:
                    self._queue.pop(highest_prio_idx)
                    self.dropped_count += 1
                else:
                    self.dropped_count += 1
                    return False

            self._queue.append(element)
            # Sortiere Queue: niedrigere Zahl = höhere Prio, dann FIFO (älteres timestamp zuerst)
            self._queue.sort(key=lambda x: (x.priority, x.timestamp))
            self.total_enqueued += 1
            self._not_empty.notify()
            return True

    async def get(self, timeout: float | None = None) -> PrioritizedItem[T]:
        async with self._not_empty:
            if not self._queue:
                if timeout is not None:
                    try:
                        await asyncio.wait_for(self._not_empty.wait_for(lambda: len(self._queue) > 0), timeout=timeout)
                    except asyncio.TimeoutError:
                        raise TimeoutError("Timeout beim Warten auf Queue-Element")
                else:
                    await self._not_empty.wait_for(lambda: len(self._queue) > 0)

            return self._queue.pop(0)

    async def size(self) -> int:
        async with self._lock:
            return len(self._queue)

    async def get_metrics(self) -> dict[str, int]:
        async with self._lock:
            p1_count = sum(1 for item in self._queue if item.priority == PriorityLevel.P1.value)
            p2_count = sum(1 for item in self._queue if item.priority == PriorityLevel.P2.value)
            p3_count = sum(1 for item in self._queue if item.priority == PriorityLevel.P3.value)
            return {
                "size": len(self._queue),
                "capacity": self.capacity,
                "p1_count": p1_count,
                "p2_count": p2_count,
                "p3_count": p3_count,
                "dropped_count": self.dropped_count,
                "total_enqueued": self.total_enqueued,
            }


class WebhookDispatchResult:
    def __init__(
        self,
        success: bool,
        status_code: int | None = None,
        attempts: int = 0,
        response_body: str | None = None,
        error_message: str | None = None,
        latency_ms: float = 0.0,
    ):
        self.success = success
        self.status_code = status_code
        self.attempts = attempts
        self.response_body = response_body
        self.error_message = error_message
        self.latency_ms = latency_ms


class WebhookDispatcher:
    """
    Orchestriert Webhook-Versand mit Circuit-Breaker, Exponential-Backoff und HTTP-Timeouts.
    """

    def __init__(
        self,
        breakers: dict[str, CircuitBreaker] | None = None,
        default_breaker_config: CircuitBreakerConfig | None = None,
        default_backoff_config: BackoffConfig | None = None,
        http_timeout_seconds: float = 10.0,
    ):
        self.breakers: dict[str, CircuitBreaker] = breakers if breakers is not None else {}
        self.default_breaker_config = default_breaker_config or CircuitBreakerConfig()
        self.default_backoff_config = default_backoff_config or BackoffConfig()
        self.http_timeout = http_timeout_seconds
        self._lock = asyncio.Lock()

    async def get_breaker(self, target_url: str) -> CircuitBreaker:
        async with self._lock:
            if target_url not in self.breakers:
                self.breakers[target_url] = CircuitBreaker(target_url, self.default_breaker_config)
            return self.breakers[target_url]

    async def dispatch(
        self,
        target_url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        backoff_config: BackoffConfig | None = None,
    ) -> WebhookDispatchResult:
        breaker = await self.get_breaker(target_url)
        cfg = backoff_config or self.default_backoff_config

        if not await breaker.can_execute():
            return WebhookDispatchResult(
                success=False,
                error_message=f"Circuit Breaker ist OPEN für {target_url}",
                attempts=0,
            )

        attempt = 0
        total_start = time.perf_counter()

        async with httpx.AsyncClient(timeout=self.http_timeout) as client:
            while attempt < cfg.max_retries:
                attempt += 1
                req_start = time.perf_counter()
                try:
                    resp = await client.post(
                        target_url,
                        json=payload,
                        headers=headers or {"Content-Type": "application/json"},
                    )
                    latency_ms = (time.perf_counter() - req_start) * 1000.0

                    if resp.status_code < 400:
                        await breaker.record_success()
                        return WebhookDispatchResult(
                            success=True,
                            status_code=resp.status_code,
                            attempts=attempt,
                            response_body=resp.text[:500],
                            latency_ms=latency_ms,
                        )

                    # 4xx Clientfehler (außer 429 Too Many Requests) werden in der Regel nicht retried
                    if 400 <= resp.status_code < 500 and resp.status_code != 429:
                        await breaker.record_failure()
                        return WebhookDispatchResult(
                            success=False,
                            status_code=resp.status_code,
                            attempts=attempt,
                            error_message=f"Client-Fehler HTTP {resp.status_code}",
                            latency_ms=latency_ms,
                        )

                    # Serverfehler (5xx) oder 429 -> Retry & Breaker Failure zählen
                    await breaker.record_failure()

                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
                    latency_ms = (time.perf_counter() - req_start) * 1000.0
                    await breaker.record_failure()
                    if attempt >= cfg.max_retries:
                        return WebhookDispatchResult(
                            success=False,
                            attempts=attempt,
                            error_message=f"Netzwerkfehler: {exc!s}",
                            latency_ms=latency_ms,
                        )

                if attempt < cfg.max_retries:
                    delay = calculate_backoff(attempt, cfg)
                    await asyncio.sleep(delay)

        total_latency = (time.perf_counter() - total_start) * 1000.0
        return WebhookDispatchResult(
            success=False,
            attempts=attempt,
            error_message="Maximale Anzahl an Retries überschritten",
            latency_ms=total_latency,
        )
