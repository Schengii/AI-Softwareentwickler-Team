"""Nexus Resilience Gateway - Kernmodul für Resilienz, Fehlertoleranz & Traffic-Control.

Implementiert:
- State-of-the-Art Circuit Breaker (CLOSED -> OPEN -> HALF-OPEN -> CLOSED)
- Token-Bucket Rate Limiter pro Mandant (Async Concurrency Safe)
- Exponential Backoff mit Random Jitter (secrets.SystemRandom())
- Asynchrone Dead-Letter-Queue (DLQ) mit manueller & automatischer Replay-Funktion
- Registry-Singletons mit Lazy-Initialisierung (Async- & Event-Loop Direktiven-konform)
"""

import asyncio
import enum
import logging
import secrets
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger("nexus_gateway.resilience")

T = TypeVar("T")


class CircuitState(str, enum.Enum):
    """Zustände des Circuit Breakers."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF-OPEN"


class CircuitBreakerOpenException(Exception):
    """Ausnahme, wenn der Circuit Breaker im Zustand OPEN ist und Aufrufe abwehrt."""
    def __init__(self, service_name: str, retry_after: float):
        self.service_name = service_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker für Dienst '{service_name}' ist OPEN. "
            f"Erneuter Versuch frühestens in {retry_after:.2f}s möglich."
        )


class CircuitBreaker:
    """
    State-of-the-Art Circuit Breaker für I/O & Upstream-Aufrufe.

    - CLOSED: Normalbetrieb. Bei Erreichen von `failure_threshold` aufeinanderfolgenden
      oder gehäuften Fehlern schaltet der Schalter auf OPEN.
    - OPEN: Anfragen scheitern sofort mit `CircuitBreakerOpenException` ohne Upstream-Last.
    - HALF-OPEN: Nach Ablauf von `recovery_timeout` wird ein Test-Aufruf durchgelassen.
      Bei Erfolg -> CLOSED. Bei Fehlschlag -> sofort wieder OPEN.
    """

    def __init__(
        self,
        service_name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exceptions: tuple = (Exception,),
    ) -> None:
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions

        self.failure_count: int = 0
        self.success_count: int = 0
        self.state: CircuitState = CircuitState.CLOSED
        self.last_state_change: float = time.monotonic()
        self.last_failure_time: float | None = None
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def is_open(self) -> bool:
        """Prüft, ob der Schalter aktuell als OPEN gilt (unter Berücksichtigung des Timeouts)."""
        if self.state == CircuitState.OPEN:
            now = time.monotonic()
            if now - self.last_state_change > self.recovery_timeout:
                return False  # Kann in HALF-OPEN übergehen
            return True
        return False

    async def call(
        self,
        coro_func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Führt eine Coroutine abgesichert über den Circuit Breaker aus."""
        lock = self._get_lock()
        async with lock:
            now = time.monotonic()
            if self.state == CircuitState.OPEN:
                if now - self.last_state_change > self.recovery_timeout:
                    logger.info(
                        "CircuitBreaker[%s]: Recovery-Timeout abgelaufen -> Wechsle zu HALF-OPEN",
                        self.service_name,
                    )
                    self.state = CircuitState.HALF_OPEN
                    self.last_state_change = now
                else:
                    remaining = self.recovery_timeout - (now - self.last_state_change)
                    raise CircuitBreakerOpenException(self.service_name, max(0.0, remaining))

        try:
            result = await coro_func(*args, **kwargs)
            async with lock:
                if self.state == CircuitState.HALF_OPEN:
                    logger.info(
                        "CircuitBreaker[%s]: Erfolgreicher Testaufruf in HALF-OPEN -> Wechsle zu CLOSED",
                        self.service_name,
                    )
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.last_state_change = time.monotonic()
                elif self.state == CircuitState.CLOSED:
                    self.failure_count = 0
            return result

        except self.expected_exceptions as exc:
            async with lock:
                self.failure_count += 1
                self.last_failure_time = time.monotonic()
                logger.warning(
                    "CircuitBreaker[%s]: Fehler aufgetreten (%s). Zähler: %d/%d",
                    self.service_name,
                    exc,
                    self.failure_count,
                    self.failure_threshold,
                )
                if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    self.last_state_change = time.monotonic()
                    logger.error(
                        "CircuitBreaker[%s]: Schwellenwert erreicht! Zustand gewechselt zu OPEN für %.1fs",
                        self.service_name,
                        self.recovery_timeout,
                    )
            raise exc

    def get_status(self) -> dict[str, Any]:
        """Gibt den Status des Circuit Breakers für Monitoring-Dashboards zurück."""
        now = time.monotonic()
        return {
            "service": self.service_name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "uptime_in_state": round(now - self.last_state_change, 2),
            "is_open": self.is_open,
        }


class TokenBucket:
    """
    Token-Bucket Algorithmus zur Ratenbegrenzung (Rate Limiting).

    Erlaubt Bursts bis zur maximalen `capacity` und füllt Tokens kontinuierlich
    mit einer Rate von `refill_rate` Tokens pro Sekunde nach.
    Verwendet `time.monotonic()` für präzise, driftfreie Zeitmessung.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_rate = float(refill_rate)
        self.last_refill = time.monotonic()
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Versucht, `tokens` aus dem Bucket zu entnehmen.
        Gibt True zurück, wenn genug Tokens vorhanden waren, sonst False.
        """
        lock = self._get_lock()
        async with lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    async def get_available_tokens(self) -> float:
        """Gibt die aktuell verfügbare Anzahl an Tokens zurück."""
        lock = self._get_lock()
        async with lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            return min(self.capacity, self.tokens + elapsed * self.refill_rate)


class TenantRateLimiter:
    """Mandantenfähiger Rate Limiter mit Token-Bucket Instanzen pro Mandant."""

    def __init__(self, default_capacity: int = 100, default_refill_rate: float = 100.0) -> None:
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self.buckets: dict[str, TokenBucket] = {}
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def check_rate_limit(
        self,
        tenant_id: str,
        capacity: int | None = None,
        refill_rate: float | None = None,
        cost: int = 1,
    ) -> bool:
        """Prüft, ob der Mandant das Rate Limit einhält."""
        lock = self._get_lock()
        async with lock:
            if tenant_id not in self.buckets:
                cap = capacity or self.default_capacity
                rate = refill_rate or self.default_refill_rate
                self.buckets[tenant_id] = TokenBucket(capacity=cap, refill_rate=rate)
            bucket = self.buckets[tenant_id]

        return await bucket.acquire(cost)


async def retry_with_backoff(
    coro_func: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 0.1,
    factor: float = 2.0,
    max_delay: float = 5.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (Exception,),
    **kwargs: Any,
) -> T:
    """
    Führt eine Coroutine mit exponentiellem Backoff und Random-Jitter aus.

    Jitter verhindert das 'Thundering-Herd'-Problem bei simultanen Retries
    mittels kryptographisch sicherem `secrets.SystemRandom()`.
    """
    delay = initial_delay
    secure_rng = secrets.SystemRandom()

    for attempt in range(max_retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except retryable_exceptions as exc:
            if attempt == max_retries:
                logger.error(
                    "Retry-Limit (%d Retries) erreicht. Aufruf schlägt endgültig fehl: %s",
                    max_retries,
                    exc,
                )
                raise exc

            # Backoff-Berechnung mit Jitter
            current_delay = min(delay, max_delay)
            if jitter:
                sleep_duration = secure_rng.uniform(0.5 * current_delay, 1.5 * current_delay)
            else:
                sleep_duration = current_delay

            logger.warning(
                "Versuch %d/%d fehlgeschlagen (%s). Warte %.3fs vor erneutem Versuch...",
                attempt + 1,
                max_retries,
                exc,
                sleep_duration,
            )
            await asyncio.sleep(sleep_duration)
            delay *= factor

    raise RuntimeError("Unerreichbarer Zustand in retry_with_backoff")


class InMemoryDLQ:
    """
    Asynchrone Dead-Letter-Queue (DLQ) für fehlgeschlagene Payloads.
    Ermöglicht manuelle und automatische Replays.
    """

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []
        self._replayed: list[dict[str, Any]] = []
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def push(
        self,
        message_id: str,
        payload: dict[str, Any],
        error: str,
        target_service: str = "unknown",
        tenant_id: str = "unknown",
    ) -> dict[str, Any]:
        """Fügt eine fehlgeschlagene Nachricht der DLQ hinzu."""
        entry = {
            "id": message_id,
            "target_service": target_service,
            "tenant_id": tenant_id,
            "payload": payload,
            "error": error,
            "timestamp": time.time(),
            "status": "FAILED",
            "retry_count": 0,
        }
        lock = self._get_lock()
        async with lock:
            self._messages.append(entry)
        logger.info("DLQ: Nachricht %s gespeichert (Dienst: %s)", message_id, target_service)
        return entry

    async def get_messages(self, status_filter: str | None = "FAILED") -> list[dict[str, Any]]:
        """Gibt gefilterte DLQ-Nachrichten zurück."""
        lock = self._get_lock()
        async with lock:
            if status_filter:
                return [m for m in self._messages if m.get("status") == status_filter]
            return list(self._messages)

    async def replay(
        self,
        message_id: str,
        dispatch_coro: Callable[[dict[str, Any]], Coroutine[Any, Any, bool]] | None = None,
    ) -> bool:
        """
        Markiert eine Nachricht als REPLAYED und führt optional den Dispatcher aus.
        """
        lock = self._get_lock()
        target_msg = None
        async with lock:
            for m in self._messages:
                if m["id"] == message_id:
                    target_msg = m
                    break

        if not target_msg:
            return False

        if dispatch_coro is not None:
            try:
                success = await dispatch_coro(target_msg["payload"])
                if not success:
                    target_msg["retry_count"] += 1
                    return False
            except Exception as e:
                logger.error("DLQ Replay für %s fehlgeschlagen: %s", message_id, e)
                target_msg["retry_count"] += 1
                return False

        async with lock:
            target_msg["status"] = "REPLAYED"
            self._replayed.append(target_msg)

        logger.info("DLQ: Nachricht %s erfolgreich replayed", message_id)
        return True


class ResilienceRegistry:
    """Zentrale Registry für Circuit Breaker und Rate Limiter."""

    def __init__(self) -> None:
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.rate_limiter = TenantRateLimiter()
        self.dlq = InMemoryDLQ()

    def get_circuit_breaker(
        self,
        service_name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> CircuitBreaker:
        """Liefert oder erstellt einen Circuit Breaker für einen Ziel-Service."""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = CircuitBreaker(
                service_name=service_name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
        return self.circuit_breakers[service_name]

    def get_all_breaker_statuses(self) -> list[dict[str, Any]]:
        """Liefert Status aller registrierten Breaker für das Monitoring Dashboard."""
        return [cb.get_status() for cb in self.circuit_breakers.values()]
