import asyncio
import logging
import secrets
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

class CircuitBreakerOpenError(Exception):
    """Wird ausgelöst, wenn der Circuit Breaker im Zustand OPEN ist."""


class CircuitBreaker:
    """
    Asynchroner In-Memory Circuit Breaker für Webhook-Ziele und I/O-Aufrufe.
    Zustände: CLOSED (normal), OPEN (blockiert Aufrufe), HALF_OPEN (Probe-Request).
    Verwendet strikt time.monotonic() für Zustands- und Cooldown-Berechnungen.
    """
    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        recovery_threshold: int = 1,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.recovery_threshold = recovery_threshold
        self.failure_count: int = 0
        self.success_count: int = 0
        self.state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_state_change: float = time.monotonic()

    def can_attempt(self) -> bool:
        now = time.monotonic()
        if self.state == "OPEN":
            if now - self.last_state_change >= self.cooldown_seconds:
                self.state = "HALF_OPEN"
                self.last_state_change = now
                logger.info("CircuitBreaker transitioned to HALF_OPEN")
                return True
            return False
        return True

    def record_success(self) -> None:
        now = time.monotonic()
        if self.state == "HALF_OPEN":
            self.success_count += 1
            if self.success_count >= self.recovery_threshold:
                self.state = "CLOSED"
                self.failure_count = 0
                self.success_count = 0
                self.last_state_change = now
                logger.info("CircuitBreaker recovered and transitioned to CLOSED")
        elif self.state == "CLOSED":
            self.failure_count = 0

    def record_failure(self) -> None:
        now = time.monotonic()
        self.failure_count += 1
        self.last_state_change = now
        if self.state in ("CLOSED", "HALF_OPEN") and self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                f"CircuitBreaker tripped to OPEN after {self.failure_count} failures. "
                f"Cooldown: {self.cooldown_seconds}s"
            )


def calculate_backoff_with_jitter(
    attempt: int,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    factor: float = 2.0,
) -> float:
    """
    Berechnet exponentielles Backoff mit Full-Jitter.
    Nutzt secrets.SystemRandom() für kryptografisch sicheren Jitter (Bandit-konform).
    """
    calculated_delay = min(max_delay, base_delay * (factor ** attempt))
    jitter = secrets.SystemRandom().uniform(0.1, calculated_delay)  # nosec B311
    return round(jitter, 3)


async def execute_with_resilience(
    coro_func: Callable[[], Coroutine[Any, Any, T]],
    circuit_breaker: CircuitBreaker | None = None,
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> tuple[bool, T | None, str | None]:
    """
    Führt eine asynchrone Coroutine mit Circuit Breaker und Exponential Backoff + Jitter aus.
    Gibt ein Tuple zurück: (success: bool, result: Optional[T], error_message: Optional[str])
    """
    if circuit_breaker and not circuit_breaker.can_attempt():
        return False, None, "Circuit breaker is OPEN - delivery short-circuited"

    last_error: str | None = None

    for attempt in range(max_retries):
        try:
            res = await coro_func()
            if circuit_breaker:
                circuit_breaker.record_success()
            return True, res, None
        except retryable_exceptions as exc:
            last_error = f"Attempt {attempt + 1}/{max_retries} failed: {type(exc).__name__}: {exc!s}"
            logger.warning(last_error)
            if circuit_breaker:
                circuit_breaker.record_failure()

            if attempt < max_retries - 1:
                delay = calculate_backoff_with_jitter(attempt, base_delay=base_delay, max_delay=max_delay)
                await asyncio.sleep(delay)

    return False, None, last_error
