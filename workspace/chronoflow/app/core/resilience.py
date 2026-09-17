"""
Resilience & Fault-Tolerance Module for ChronoFlow Saga Engine.
Implements:
- Endpoint/Action Circuit Breaker with CLOSED, OPEN, HALF_OPEN states (time.monotonic based)
- Exponential Backoff with Jitter (Bandit-safe via secrets.SystemRandom)
- Step retry decorator and resilient execution wrapper
- Compensation tracking and failure recovery
"""
import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger("chronoflow.resilience")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Geworfen, wenn der Circuit Breaker im Zustand OPEN ist und Aufrufe blockiert."""


class CircuitBreaker:
    """
    In-Memory Circuit Breaker für Saga-Schritte und externe Aufrufe.
    Nutzt strikt time.monotonic() für Zustandsprüfungen gemäß Async-Direktive.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        cooldown_seconds: float = 10.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count: int = 0
        self.state: CircuitState = CircuitState.CLOSED
        self.last_failure_time: float = 0.0

    def can_attempt(self) -> bool:
        """Prüft, ob ein Aufruf zulässig ist oder im Cooldown-Fenster blockiert wird."""
        now = time.monotonic()
        if self.state == CircuitState.OPEN:
            if now - self.last_failure_time >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                logger.info("CircuitBreaker '%s' wechselt zu HALF_OPEN (Probe-Request erlaubt)", self.name)
                return True
            return False
        return True

    def record_success(self) -> None:
        """Registriert einen erfolgreichen Durchlauf und setzt den Breaker zurück."""
        if self.state != CircuitState.CLOSED:
            logger.info("CircuitBreaker '%s' erfolgreich erholt -> CLOSED", self.name)
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Registriert einen Fehlschlag und öffnet den Breaker bei Schwellenwert-Überschreitung."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        logger.warning(
            "CircuitBreaker '%s' Fehler registriert (%d/%d)",
            self.name,
            self.failure_count,
            self.failure_threshold,
        )
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error("CircuitBreaker '%s' hat Schwellenwert erreicht -> OPEN", self.name)


class ResilientStepExecutor:
    """
    Führt Saga-Schritte mit Exponential Backoff, Jitter und Circuit-Breaker-Schutz aus.
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker | None = None,
        max_retries: int = 3,
        initial_backoff: float = 0.1,
        backoff_multiplier: float = 2.0,
        max_backoff: float = 2.0,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ):
        self.cb = circuit_breaker or CircuitBreaker()
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.backoff_multiplier = backoff_multiplier
        self.max_backoff = max_backoff
        self.retryable_exceptions = retryable_exceptions
        self.rng = secrets.SystemRandom()

    async def execute(self, action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Führt eine synchrone oder asynchrone Funktion fehlertolerant aus.
        """
        if not self.cb.can_attempt():
            raise CircuitBreakerOpenError(
                f"Circuit Breaker '{self.cb.name}' ist OPEN. Aufruf temporär blockiert."
            )

        attempt = 0
        last_exception: Exception | None = None

        while attempt <= self.max_retries:
            try:
                attempt += 1
                if asyncio.iscoroutinefunction(action):
                    res = await action(*args, **kwargs)
                else:
                    res = action(*args, **kwargs)

                self.cb.record_success()
                return res
            except self.retryable_exceptions as exc:
                last_exception = exc
                self.cb.record_failure()

                if attempt > self.max_retries or not self.cb.can_attempt():
                    logger.error(
                        "ResilientStepExecutor: Schritt nach %d Versuchen abgebrochen. Fehler: %s",
                        attempt,
                        str(exc),
                    )
                    break

                # Exponential Backoff mit sicherem Jitter (0.8 bis 1.2)
                jitter = self.rng.uniform(0.8, 1.2)
                delay = min(
                    self.initial_backoff * (self.backoff_multiplier ** (attempt - 1)) * jitter,
                    self.max_backoff,
                )
                logger.warning(
                    "Retry-Versuch %d/%d nach %.3fs Verzögerung wegen: %s",
                    attempt,
                    self.max_retries,
                    delay,
                    str(exc),
                )
                await asyncio.sleep(delay)

        raise last_exception if last_exception else RuntimeError("Unerwarteter Abbruch im ResilientStepExecutor")


# Global verwaltete Breaker-Registry
_breakers: dict[str, CircuitBreaker] = {}


def get_or_create_circuit_breaker(name: str, threshold: int = 3, cooldown: float = 10.0) -> CircuitBreaker:
    """Holt oder erzeugt einen Circuit Breaker für einen Service/Schrittnamen."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name, failure_threshold=threshold, cooldown_seconds=cooldown)
    return _breakers[name]
