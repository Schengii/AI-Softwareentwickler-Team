"""HyperionSentinel - Resilient Sliding Window Rate Limiter.

Implementiert:
- Asynchroner Sliding-Window-Counter-Algorithmus
- Asynchroner Circuit Breaker mit Graceful Degradation
- Speichereffizienter In-Memory TTL/LRU-Fallback
- Konfigurierbarer Burst-Faktor, Exponential Backoff & Jitter
"""

import asyncio
import logging
import math
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger("hyperionsentinel.rate_limiter")


class CircuitState(str, Enum):
    """Zustaende des Circuit Breakers."""
    CLOSED = "CLOSED"
    HALF_OPEN = "HALF_OPEN"
    OPEN = "OPEN"


class CircuitBreakerOpenError(Exception):
    """Ausnahme wenn der Circuit Breaker geoffnet ist."""


@dataclass
class RateLimitResult:
    """Ergebnis einer Rate-Limit Pruefung."""
    allowed: bool
    limit: int
    remaining: int
    reset_epoch_seconds: int
    retry_after_seconds: float
    current_usage: float
    degraded_mode: bool = False
    source: str = "primary"


class CircuitBreaker:
    """Resilienter asynchroner Circuit Breaker fuer I/O- und Speicher-Engines.
    
    Verwendet strikt time.monotonic() gemaess Async & Event-Loop Direktive.
    """

    def __init__(
        self,
        name: str = "storage_circuit_breaker",
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 10.0,
        half_open_max_trials: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_max_trials = half_open_max_trials
        
        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.success_count: int = 0
        self.last_failure_time: float = 0.0
        self.opened_at: float = 0.0
        self._lock = asyncio.Lock()

    def is_available(self) -> bool:
        """Prueft synchron basierend auf time.monotonic(), ob der Breaker Anfragen zulaesst."""
        now = time.monotonic()
        if self.state == CircuitState.OPEN:
            if now - self.opened_at >= self.recovery_timeout_seconds:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                logger.info("CircuitBreaker '%s' wechselt von OPEN -> HALF_OPEN (Probe-Phase)", self.name)
                return True
            return False
        return True

    async def record_success(self) -> None:
        """Registriert einen erfolgreichen I/O-Aufruf."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.half_open_max_trials:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    logger.info("CircuitBreaker '%s' schliesst sich vollstaendig (HALF_OPEN -> CLOSED)", self.name)
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    async def record_failure(self, exc: Exception) -> None:
        """Registriert einen fehlgeschlagenen Aufruf und oeffnet ggf. den Breaker."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()
            logger.warning(
                "CircuitBreaker '%s' Fehler erfasst: %s (Fehleranzahl: %d/%d)",
                self.name,
                str(exc),
                self.failure_count,
                self.failure_threshold,
            )
            if self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN) and self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()
                logger.error(
                    "CircuitBreaker '%s' hat den Schwellenwert ueberschritten und ist nun OPEN!",
                    self.name,
                )

    async def execute(self, coro_func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Fuehrt ein Coroutine-Target geschuetzt aus."""
        if not self.is_available():
            raise CircuitBreakerOpenError(f"CircuitBreaker '{self.name}' ist OPEN.")

        try:
            result = await coro_func(*args, **kwargs)
            await self.record_success()
            return result
        except Exception as exc:
            await self.record_failure(exc)
            raise


class InMemorySlidingWindowCache:
    """Speichereffizienter LRU/TTL Sliding-Window Cache fuer Graceful Degradation."""

    def __init__(self, capacity: int = 10000, ttl_seconds: float = 300.0) -> None:
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        # key: (sub_window_epoch, count, last_access)
        self._data: OrderedDict[str, dict[int, int]] = OrderedDict()
        self._access_times: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _cleanup_expired(self, now: float) -> None:
        """Entfernt abgelaufene Eintraege via LRU/TTL."""
        expired_keys = [
            key for key, last_acc in self._access_times.items()
            if now - last_acc > self.ttl_seconds
        ]
        for k in expired_keys:
            self._data.pop(k, None)
            self._access_times.pop(k, None)

        while len(self._data) > self.capacity:
            oldest_key, _ = self._data.popitem(last=False)
            self._access_times.pop(oldest_key, None)

    async def get_and_increment(
        self,
        key: str,
        current_sub_window: int,
        prev_sub_window: int,
        now: float,
    ) -> tuple[int, int]:
        """Inkrementiert das aktuelle Subfenster und gibt (prev_count, current_count) zurueck."""
        async with self._lock:
            self._cleanup_expired(now)
            self._access_times[key] = now
            if key in self._data:
                self._data.move_to_end(key)
            else:
                self._data[key] = {}

            bucket = self._data[key]
            
            # Altes Fenster loeschen wenn aelter als prev_sub_window
            obsolete_windows = [w for w in bucket if w < prev_sub_window]
            for w in obsolete_windows:
                del bucket[w]

            prev_count = bucket.get(prev_sub_window, 0)
            bucket[current_sub_window] = bucket.get(current_sub_window, 0) + 1
            current_count = bucket[current_sub_window]

            return prev_count, current_count


class SlidingWindowRateLimiter:
    """Asynchroner Sliding-Window Counter mit Circuit Breaker und In-Memory LRU/TTL Fallback.
    
    Erfuellt interface_contract.json: app.services.rate_limiter:SlidingWindowRateLimiter
    """

    def __init__(
        self,
        primary_storage: Any | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        in_memory_fallback: InMemorySlidingWindowCache | None = None,
        default_window_seconds: int = 60,
    ) -> None:
        self.primary_storage = primary_storage
        self.circuit_breaker = circuit_breaker or CircuitBreaker(name="rate_limit_primary_storage")
        self.fallback_cache = in_memory_fallback or InMemorySlidingWindowCache()
        self.default_window_seconds = default_window_seconds

    def calculate_jitter_backoff(self, attempt: int, base_delay: float = 0.1, max_delay: float = 2.0) -> float:
        """Berechnet exponentielles Backoff mit Jitter (Bandit B311-compliant via secrets)."""
        backoff = min(max_delay, base_delay * (2 ** attempt))
        jitter = secrets.SystemRandom().uniform(0.0, backoff * 0.5)
        return backoff + jitter

    async def is_rate_limited(
        self,
        identifier: str,
        limit: int,
        window_seconds: int | None = None,
        burst_multiplier: float = 1.0,
    ) -> RateLimitResult:
        """Prueft das Rate-Limit via gewichtetem Sliding Window Counter mit Graceful Degradation."""
        window_size = window_seconds or self.default_window_seconds
        effective_limit = math.ceil(limit * max(1.0, burst_multiplier))

        now_mono = time.monotonic()
        now_wall = time.time()

        # Zeitschlitze berechnen
        sub_window_size = window_size
        current_window = int(now_wall // sub_window_size)
        prev_window = current_window - 1
        time_into_current_window = now_wall % sub_window_size
        window_weight = (sub_window_size - time_into_current_window) / sub_window_size

        degraded_mode = False
        source = "primary"
        prev_count = 0
        curr_count = 0

        # Versuch ueber primaeren Speicher, abgesichert durch Circuit Breaker
        use_fallback = not self.circuit_breaker.is_available() or self.primary_storage is None

        if not use_fallback and self.primary_storage is not None:
            try:
                # Primaere asynchrone Operation (z. B. Redis / Distributed Engine)
                async def _primary_call() -> tuple[int, int]:
                    # Aufruf an primary_storage Interface falls vorhanden
                    return await self.primary_storage.get_and_increment(
                        key=identifier,
                        current_sub_window=current_window,
                        prev_sub_window=prev_window,
                        now=now_mono,
                    )
                
                prev_count, curr_count = await self.circuit_breaker.execute(_primary_call)
                source = "primary"
            except Exception as exc:  # noqa: BLE001 - Fange Ausfall des primaeren Speichers ab fuer Graceful Fallback
                logger.warning("Primaere Speicher-Engine ausgefallen (%s). Umschaltung auf In-Memory LRU/TTL Fallback!", str(exc))
                use_fallback = True

        if use_fallback:
            degraded_mode = True
            source = "in_memory_fallback"
            prev_count, curr_count = await self.fallback_cache.get_and_increment(
                key=identifier,
                current_sub_window=current_window,
                prev_sub_window=prev_window,
                now=now_mono,
            )

        # Sliding Window Approximation
        estimated_count = (prev_count * window_weight) + curr_count
        remaining = max(0, int(effective_limit - estimated_count))
        allowed = estimated_count <= effective_limit

        # Reset-Zeitpunkt & Retry-After berechnen
        reset_epoch = int(now_wall + (sub_window_size - time_into_current_window))
        retry_after = 0.0 if allowed else max(0.1, round(sub_window_size - time_into_current_window, 2))

        return RateLimitResult(
            allowed=allowed,
            limit=effective_limit,
            remaining=remaining,
            reset_epoch_seconds=reset_epoch,
            retry_after_seconds=retry_after,
            current_usage=round(estimated_count, 2),
            degraded_mode=degraded_mode,
            source=source,
        )
