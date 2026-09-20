import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from app.core.errors import SynapseException

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(SynapseException):
    def __init__(self, message: str = "Circuit breaker is open. Upstream service unavailable.", retry_after: float = 0.0) -> None:
        super().__init__(
            status_code=503,
            code="CIRCUIT_OPEN",
            message=message,
            details={"retry_after_seconds": round(retry_after, 2)}
        )


class CircuitBreaker:
    """
    Thread-/Task-sicherer Circuit Breaker mit Closed, Open, Half-Open Status,
    exponentiellem Backoff bei anhaltenden Fehlern und Jitter.
    """
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_trials: int = 3,
        backoff_multiplier: float = 1.5,
        max_recovery_timeout: float = 300.0,
        expected_exceptions: tuple[type[BaseException], ...] = (Exception,),
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.base_recovery_timeout = recovery_timeout
        self.current_recovery_timeout = recovery_timeout
        self.half_open_max_trials = max(1, half_open_max_trials)
        self.backoff_multiplier = backoff_multiplier
        self.max_recovery_timeout = max_recovery_timeout
        self.expected_exceptions = expected_exceptions

        self.state = CircuitState.CLOSED
        self.failures = 0
        self.consecutive_opens = 0
        self.last_failure_time: float = 0.0
        self.half_open_success_count = 0
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _calculate_backoff_timeout(self) -> float:
        # Exponentieller Backoff basierend auf Anzahl aufeinanderfolgender Openings mit Jitter
        factor = self.backoff_multiplier ** min(self.consecutive_opens, 6)
        calculated = min(self.base_recovery_timeout * factor, self.max_recovery_timeout)
        # Jitter hinzufügen: +/- 10% mittels secrets.SystemRandom()
        jitter = secrets.SystemRandom().uniform(0.9, 1.1)
        return round(calculated * jitter, 3)

    async def call(self, func: Callable[..., Any], *args: Any, timeout: float | None = None, **kwargs: Any) -> Any:
        lock = self._get_lock()
        async with lock:
            now = time.monotonic()
            if self.state == CircuitState.OPEN:
                elapsed = now - self.last_failure_time
                if elapsed >= self.current_recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_success_count = 0
                    logger.info("Circuit breaker transitioning to HALF_OPEN after cooldown")
                else:
                    remaining = max(0.0, self.current_recovery_timeout - elapsed)
                    raise CircuitBreakerOpenException(retry_after=remaining)

        try:
            if timeout is not None and timeout > 0:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
            else:
                result = await func(*args, **kwargs)

            async with lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.half_open_success_count += 1
                    if self.half_open_success_count >= self.half_open_max_trials:
                        self.state = CircuitState.CLOSED
                        self.failures = 0
                        self.consecutive_opens = 0
                        self.current_recovery_timeout = self.base_recovery_timeout
                        logger.info("Circuit breaker fully recovered: transitioning to CLOSED")
                elif self.state == CircuitState.CLOSED:
                    self.failures = 0

            return result

        except self.expected_exceptions as e:
            async with lock:
                self.failures += 1
                self.last_failure_time = time.monotonic()

                if self.state == CircuitState.HALF_OPEN or self.failures >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    self.consecutive_opens += 1
                    self.current_recovery_timeout = self._calculate_backoff_timeout()
                    logger.warning(
                        "Circuit breaker tripped to OPEN. Failures: %d, Consecutive Opens: %d, Next Cooldown: %.2fs",
                        self.failures, self.consecutive_opens, self.current_recovery_timeout
                    )

            if isinstance(e, SynapseException):
                raise e

            raise SynapseException(
                status_code=502,
                code="UPSTREAM_ERROR",
                message="Upstream service call failed.",
                details={"reason": str(e), "circuit_state": self.state.value}
            ) from e


class CircuitBreakerRegistry:
    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def get_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_trials: int = 3,
        backoff_multiplier: float = 1.5,
        max_recovery_timeout: float = 300.0,
    ) -> CircuitBreaker:
        lock = self._get_lock()
        async with lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    half_open_max_trials=half_open_max_trials,
                    backoff_multiplier=backoff_multiplier,
                    max_recovery_timeout=max_recovery_timeout,
                )
            return self._breakers[name]

    async def get_all_states(self) -> dict[str, str]:
        lock = self._get_lock()
        async with lock:
            return {name: breaker.state.value for name, breaker in self._breakers.items()}


circuit_breaker_registry = CircuitBreakerRegistry()
