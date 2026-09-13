"""Circuit-Breaker State Machine und Outbox-Retry mit adaptivem Jitter-Backoff.

Vortex Circuit - High-Performance Resilience Engine.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger("vortex_circuit.circuit_breaker")

T = TypeVar("T")


class CircuitState(str, Enum):
    """Dreistufige Circuit-Breaker State Machine."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenException(Exception):
    """Exception geworfen, wenn Aufrufe wegen geöffnetem Circuit geblockt werden (HTTP 503 Fast-Fail)."""
    def __init__(self, service_name: str, cooldown_remaining: float, message: str | None = None):
        self.service_name = service_name
        self.cooldown_remaining = max(0.0, cooldown_remaining)
        super().__init__(
            message or f"Circuit breaker for '{service_name}' is OPEN. Cooldown remaining: {self.cooldown_remaining:.2f}s"
        )


@dataclass
class CircuitBreakerConfig:
    """Konfiguration für die Circuit-Breaker State Machine."""
    failure_threshold: int = 5
    consecutive_failures: int = 3
    cooldown_seconds: float = 30.0
    half_open_success_threshold: int = 3
    rolling_window_seconds: float = 60.0
    error_rate_threshold: float = 0.5  # 50%


@dataclass
class RequestMetric:
    timestamp: float
    success: bool
    latency_ms: float = 0.0


class CircuitBreaker:
    """Asynchrone dreistufige Circuit-Breaker State Machine (CLOSED, OPEN, HALF-OPEN)."""

    def __init__(
        self,
        service_name: str,
        config: CircuitBreakerConfig | None = None,
        on_state_change: Callable[[CircuitState, CircuitState], None] | None = None,
    ):
        self.service_name = service_name
        self.config = config or CircuitBreakerConfig()
        self.on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._half_open_success_count: int = 0
        self._last_state_change: float = time.time()
        self._rolling_window: list[RequestMetric] = []
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    def _trim_rolling_window(self, now: float) -> None:
        threshold = now - self.config.rolling_window_seconds
        self._rolling_window = [m for m in self._rolling_window if m.timestamp >= threshold]

    def _transition_to(self, target_state: CircuitState) -> None:
        if self._state == target_state:
            return
        old_state = self._state
        self._state = target_state
        self._last_state_change = time.time()
        logger.warning(
            "CircuitBreaker [%s]: State transition %s -> %s",
            self.service_name,
            old_state.value,
            target_state.value,
        )
        if self.on_state_change:
            try:
                self.on_state_change(old_state, target_state)
            except Exception as exc:  # noqa: BLE001
                logger.error("Error in on_state_change callback: %s", exc)

    async def allow_request(self) -> bool:
        """Prüft, ob der nächste Aufruf passieren darf oder fast-failed."""
        async with self._lock:
            now = time.time()
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                time_in_open = now - self._last_state_change
                if time_in_open >= self.config.cooldown_seconds:
                    self._transition_to(CircuitState.HALF_OPEN)
                    self._half_open_success_count = 0
                    return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                return True

            return False

    async def record_success(self, latency_ms: float = 0.0) -> None:
        """Registriert einen erfolgreichen Durchlauf."""
        async with self._lock:
            now = time.time()
            self._trim_rolling_window(now)
            self._rolling_window.append(RequestMetric(timestamp=now, success=True, latency_ms=latency_ms))

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_success_count += 1
                if self._half_open_success_count >= self.config.half_open_success_threshold:
                    self._consecutive_failures = 0
                    self._half_open_success_count = 0
                    self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                self._consecutive_failures = 0

    async def record_failure(self, exc: BaseException | None = None) -> None:
        """Registriert einen fehlerhaften Aufruf."""
        async with self._lock:
            now = time.time()
            self._trim_rolling_window(now)
            self._rolling_window.append(RequestMetric(timestamp=now, success=False))
            self._consecutive_failures += 1

            if self._state == CircuitState.HALF_OPEN:
                # Ein einzelner Fehler in HALF-OPEN schlägt sofort wieder zurück auf OPEN
                self._half_open_success_count = 0
                self._transition_to(CircuitState.OPEN)
                return

            if self._state == CircuitState.CLOSED:
                # Prüfe Schwellenwert Consecutive Failures
                if self._consecutive_failures >= self.config.consecutive_failures:
                    self._transition_to(CircuitState.OPEN)
                    return

                # Prüfe Schwellenwert Rolling Window Error Rate
                total = len(self._rolling_window)
                if total >= self.config.failure_threshold:
                    fails = sum(1 for m in self._rolling_window if not m.success)
                    error_rate = fails / total
                    if error_rate >= self.config.error_rate_threshold:
                        self._transition_to(CircuitState.OPEN)

    def remaining_cooldown(self) -> float:
        """Restliche Cooldown-Zeit in Sekunden bei Zustand OPEN."""
        if self._state != CircuitState.OPEN:
            return 0.0
        elapsed = time.time() - self._last_state_change
        return max(0.0, self.config.cooldown_seconds - elapsed)

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: Callable[[BaseException], Awaitable[T]] | None = None,
        **kwargs: Any,
    ) -> T:
        """Führt eine asynchrone Funktion geschützt durch den Circuit Breaker aus."""
        if not await self.allow_request():
            remaining = self.remaining_cooldown()
            exc = CircuitOpenException(self.service_name, remaining)
            if fallback:
                return await fallback(exc)
            raise exc

        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            latency_ms = (time.perf_counter() - start) * 1000.0
            await self.record_success(latency_ms=latency_ms)
            return result
        except BaseException as exc:
            await self.record_failure(exc)
            if fallback:
                return await fallback(exc)
            raise


# ---------------------------------------------------------------------------
# Outbox-Retry & Exponential Backoff mit Full Jitter
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    """Konfiguration für exponentielles Backoff mit Jitter."""
    max_retries: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    factor: float = 2.0
    jitter_type: str = "full"  # "full", "equal", oder "decorrelated"


def compute_backoff_with_jitter(
    attempt: int,
    config: RetryConfig | None = None,
    previous_delay: float = 1.0,
) -> float:
    """Berechnet asynchrones exponentielles Backoff mit Jitter (AWS Architecture Strategy).

    Full Jitter: V = random_between(0, min(max_delay, base * factor^attempt))
    Equal Jitter: V = (temp / 2) + random_between(0, temp / 2)
    """
    cfg = config or RetryConfig()
    if attempt <= 0:
        return 0.0

    exp_delay = min(cfg.max_delay, cfg.base_delay * (cfg.factor ** (attempt - 1)))

    if cfg.jitter_type == "full":
        return random.uniform(0.0, exp_delay)
    elif cfg.jitter_type == "equal":
        half = exp_delay / 2.0
        return half + random.uniform(0.0, half)
    elif cfg.jitter_type == "decorrelated":
        return min(cfg.max_delay, random.uniform(cfg.base_delay, previous_delay * 3.0))
    return exp_delay


async def retry_with_jitter(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    config: RetryConfig | None = None,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, float, BaseException], None] | None = None,
    **kwargs: Any,
) -> T:
    """Führt eine Operation mit exponentiellem Backoff und Jitter wiederholt aus."""
    cfg = config or RetryConfig()
    attempt = 0
    last_delay = cfg.base_delay

    while True:
        try:
            return await func(*args, **kwargs)
        except retry_exceptions as exc:
            attempt += 1
            if attempt > cfg.max_retries:
                logger.error(
                    "Retry-Limit erreicht (%d/%d Versuche). Abbruch mit: %s",
                    attempt - 1,
                    cfg.max_retries,
                    exc,
                )
                raise exc

            delay = compute_backoff_with_jitter(attempt, cfg, previous_delay=last_delay)
            last_delay = delay
            if on_retry:
                on_retry(attempt, delay, exc)
            else:
                logger.warning(
                    "Versuch %d/%d fehlgeschlagen: %s. Warte %.2fs (Backoff mit Jitter)...",
                    attempt,
                    cfg.max_retries,
                    exc,
                    delay,
                )
            await asyncio.sleep(delay)
