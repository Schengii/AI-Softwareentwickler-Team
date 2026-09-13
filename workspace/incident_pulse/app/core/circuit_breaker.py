"""Resilience & Circuit-Breaker Modul für externe Webhook-Aufrufe und Drittanbieter-Services.

Implementiert:
- Zustände: CLOSED, OPEN, HALF_OPEN
- Failure-Threshold & Recovery-Timeout
- Exponentielles Backoff mit Jitter (secrets.SystemRandom)
- In-Memory Fallback-Cache und Dead-Letter-Queue (DLQ)
- Async Aufruf-Wrapper mit Graceful Degradation
"""

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar

import httpx

logger = logging.getLogger("incidentpulse.resilience")

T = TypeVar("T")


class CircuitState(str, Enum):
    """Zustände des Circuit-Breakers."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(Exception):
    """Ausgelöst wenn der Circuit Breaker im Status OPEN ist."""
    def __init__(self, message: str = "Circuit breaker is OPEN - call rejected", retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class FallbackRecord:
    """Eintrag im Fallback-Cache oder DLQ."""
    key: str
    data: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempts: int = 0
    last_error: str | None = None


class FallbackCache:
    """Thread-sicherer In-Memory Fallback-Cache und Dead-Letter-Queue (DLQ)."""

    def __init__(self, max_items: int = 1000):
        self._cache: dict[str, FallbackRecord] = {}
        self._dlq: list[FallbackRecord] = []
        self._max_items = max_items
        self._lock = asyncio.Lock()

    async def put(self, key: str, data: Any, error: str | None = None) -> FallbackRecord:
        """Speichert Daten im Fallback-Cache."""
        async with self._lock:
            record = FallbackRecord(key=key, data=data, last_error=error)
            if len(self._cache) >= self._max_items:
                oldest_key = next(iter(self._cache))
                self._cache.pop(oldest_key, None)
            self._cache[key] = record
            return record

    async def get(self, key: str) -> Any | None:
        """Holt Daten aus dem Fallback-Cache."""
        async with self._lock:
            record = self._cache.get(key)
            return record.data if record else None

    async def add_to_dlq(self, key: str, data: Any, error: str, attempts: int = 1) -> None:
        """Fügt endgültig fehlgeschlagene Payloads der Dead-Letter-Queue hinzu."""
        async with self._lock:
            record = FallbackRecord(key=key, data=data, attempts=attempts, last_error=error)
            self._dlq.append(record)
            if len(self._dlq) > self._max_items:
                self._dlq.pop(0)

    async def get_dlq(self) -> list[dict[str, Any]]:
        """Gibt DLQ-Einträge zurück."""
        async with self._lock:
            return [
                {
                    "key": r.key,
                    "data": r.data,
                    "created_at": r.created_at.isoformat(),
                    "attempts": r.attempts,
                    "last_error": r.last_error,
                }
                for r in self._dlq
            ]


class CircuitBreaker:
    """Asynchroner Circuit Breaker mit Retry, Jitter und Fallback-Cache."""

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
        half_open_success_threshold: int = 2,
        cache: FallbackCache | None = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_success_threshold = half_open_success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_state_change = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0.0
        self._lock = asyncio.Lock()
        self.cache = cache or FallbackCache()

    @property
    def state(self) -> CircuitState:
        return self._state

    def _calculate_jitter(self, base_delay: float) -> float:
        """Berechnet Full Jitter via secrets.SystemRandom für Bandit-Konformität."""
        rnd = secrets.SystemRandom()
        return rnd.uniform(0, base_delay)

    async def _transition_to(self, new_state: CircuitState) -> None:
        """Führt Zustandswechsel durch und protokolliert ihn."""
        old_state = self._state
        self._state = new_state
        self._last_state_change = asyncio.get_event_loop().time()
        logger.warning(
            "CircuitBreaker [%s]: Zustandswechsel von %s nach %s",
            self.name,
            old_state.value,
            new_state.value,
        )

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: Callable[..., Awaitable[T]] | None = None,
        cache_key: str | None = None,
        **kwargs: Any,
    ) -> T:
        """Führt die übergebene async-Funktion unter Schutz des Circuit Breakers aus."""
        now = asyncio.get_event_loop().time()

        async with self._lock:
            # Überprüfe Wechsel OPEN -> HALF_OPEN
            if self._state == CircuitState.OPEN:
                if now - self._last_state_change >= self.recovery_timeout:
                    await self._transition_to(CircuitState.HALF_OPEN)
                    self._success_count = 0
                else:
                    time_remaining = self.recovery_timeout - (now - self._last_state_change)
                    if fallback:
                        logger.info("CircuitBreaker [%s] OPEN. Nutze Fallback.", self.name)
                        return await fallback(*args, **kwargs)
                    if cache_key:
                        cached_val = await self.cache.get(cache_key)
                        if cached_val is not None:
                            logger.info("CircuitBreaker [%s] OPEN. Nutze Fallback-Cache für %s.", self.name, cache_key)
                            return cached_val
                    raise CircuitBreakerOpenException(
                        f"Circuit breaker '{self.name}' is OPEN", retry_after=time_remaining
                    )

        # Versuch der Ausführung
        try:
            result = await func(*args, **kwargs)
            await self._on_success(cache_key=cache_key, result=result)
            return result
        except Exception as exc:
            await self._on_failure(exc, cache_key=cache_key, args=args, kwargs=kwargs)
            if fallback:
                logger.info("Aufruf fehlgeschlagen. Nutze Fallback für CircuitBreaker [%s].", self.name)
                return await fallback(*args, **kwargs)
            if cache_key:
                cached_val = await self.cache.get(cache_key)
                if cached_val is not None:
                    logger.info("Aufruf fehlgeschlagen. Liefere Cache-Fallback für %s.", cache_key)
                    return cached_val
            raise

    async def _on_success(self, cache_key: str | None = None, result: Any = None) -> None:
        """Behandelt erfolgreichen Aufruf."""
        async with self._lock:
            if cache_key and result is not None:
                await self.cache.put(cache_key, result)

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_success_threshold:
                    self._failure_count = 0
                    await self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    async def _on_failure(
        self,
        exc: Exception,
        cache_key: str | None = None,
        args: Any = None,
        kwargs: Any = None,
    ) -> None:
        """Behandelt fehlschlagenden Aufruf."""
        async with self._lock:
            self._failure_count += 1
            logger.warning(
                "CircuitBreaker [%s] Fehler %d/%d: %s",
                self.name,
                self._failure_count,
                self.failure_threshold,
                str(exc),
            )

            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                await self._transition_to(CircuitState.OPEN)

        # Bei anhaltendem Fehler in DLQ ablegen falls Cache-Key vorhanden
        if cache_key:
            payload = {"args": [str(a) for a in args] if args else [], "kwargs": kwargs or {}}
            await self.cache.add_to_dlq(cache_key, payload, error=str(exc), attempts=self._failure_count)


class WebhookClient:
    """Resilienter HTTP-Client für externe Webhooks mit Circuit Breaker und Backoff."""

    def __init__(
        self,
        circuit_breaker: CircuitBreaker | None = None,
        timeout: float = 4.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ):
        self.circuit_breaker = circuit_breaker or CircuitBreaker(name="webhook_client")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    async def send_webhook(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Sendet Webhook mit Retry, Backoff, Jitter und Circuit-Breaker-Schutz."""
        cache_key = f"webhook:{url}"

        async def _execute_with_retry() -> dict[str, Any]:
            last_err: Exception | None = None
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for attempt in range(1, self.max_retries + 1):
                    try:
                        resp = await client.post(url, json=payload, headers=headers or {})
                        resp.raise_for_status()
                        return {"status": resp.status_code, "body": resp.json() if resp.content else {}}
                    except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                        last_err = e
                        if attempt == self.max_retries:
                            raise
                        # Exponentielles Backoff mit Jitter
                        delay = (self.backoff_base * (2 ** (attempt - 1))) + self.circuit_breaker._calculate_jitter(0.2)
                        logger.warning(
                            "Webhook-Versuch %d fehlgeschlagen für %s. Retry in %.2fs (Grund: %s)",
                            attempt,
                            url,
                            delay,
                            str(e),
                        )
                        await asyncio.sleep(delay)
            if last_err:
                raise last_err
            return {"status": 200, "body": {}}

        async def _fallback_handler() -> dict[str, Any]:
            """Graceful Degradation Fallback: In Dead-Letter-Queue einreihen."""
            logger.info("Webhook-Degradation: Caching Payload für späteren Versand.")
            await self.circuit_breaker.cache.add_to_dlq(cache_key, payload, error="Circuit Open / Fallback Active")
            return {
                "status": 202,
                "degraded": True,
                "message": "Webhook in DLQ eingereiht - externer Service aktuell nicht erreichbar.",
            }

        return await self.circuit_breaker.call(
            _execute_with_retry,
            fallback=_fallback_handler,
            cache_key=cache_key,
        )


# Globale Instanz für einfache Wiederverwendung im System
default_webhook_cb = CircuitBreaker(name="global_webhook_breaker", failure_threshold=3, recovery_timeout=5.0)
default_webhook_client = WebhookClient(circuit_breaker=default_webhook_cb)
