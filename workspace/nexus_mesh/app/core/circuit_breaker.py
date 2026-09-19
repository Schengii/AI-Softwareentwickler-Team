import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Wird ausgelöst, wenn der Circuit Breaker im OPEN Zustand ist."""
    def __init__(self, service: str, retry_after: float):
        super().__init__(f"Circuit breaker for service '{service}' is OPEN. Retry after {retry_after:.1f}s")
        self.service = service
        self.retry_after = retry_after


class ServiceBreakerState(BaseModel):
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    last_state_change: float = Field(default_factory=time.monotonic)


class CircuitBreaker:
    """
    Stateful Circuit Breaker Pattern (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).
    Nutzt time.monotonic() für alle Zeit- und Cooldown-Berechnungen.
    """
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_success_threshold: int = 2,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_success_threshold = half_open_success_threshold
        self._services: dict[str, ServiceBreakerState] = {}

    def _get_service_state(self, service: str) -> ServiceBreakerState:
        if service not in self._services:
            self._services[service] = ServiceBreakerState()
        return self._services[service]

    def get_state(self, service: str) -> CircuitState:
        s = self._get_service_state(service)
        now = time.monotonic()

        if s.state == CircuitState.OPEN:
            # Prüfe, ob Recovery Timeout abgelaufen ist -> Übergang zu HALF_OPEN
            if s.last_failure_time and (now - s.last_failure_time >= self.recovery_timeout):
                s.state = CircuitState.HALF_OPEN
                s.success_count = 0
                s.last_state_change = now
        return s.state

    def can_execute(self, service: str) -> bool:
        state = self.get_state(service)
        return state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def remaining_recovery_time(self, service: str) -> float:
        s = self._get_service_state(service)
        if s.state == CircuitState.OPEN and s.last_failure_time:
            remaining = self.recovery_timeout - (time.monotonic() - s.last_failure_time)
            return max(0.0, remaining)
        return 0.0

    def record_success(self, service: str) -> None:
        s = self._get_service_state(service)
        now = time.monotonic()
        if s.state == CircuitState.HALF_OPEN:
            s.success_count += 1
            if s.success_count >= self.half_open_success_threshold:
                s.state = CircuitState.CLOSED
                s.failure_count = 0
                s.success_count = 0
                s.last_state_change = now
        elif s.state == CircuitState.CLOSED:
            s.failure_count = 0

    def record_failure(self, service: str = "default") -> None:
        s = self._get_service_state(service)
        now = time.monotonic()
        s.failure_count += 1
        s.last_failure_time = now

        if s.state == CircuitState.HALF_OPEN:
            s.state = CircuitState.OPEN
            s.last_state_change = now
        elif s.state == CircuitState.CLOSED:
            if s.failure_count >= self.failure_threshold:
                s.state = CircuitState.OPEN
                s.last_state_change = now

    def check_or_raise(self, service: str) -> None:
        if not self.can_execute(service):
            retry_after = self.remaining_recovery_time(service)
            raise CircuitOpenError(service=service, retry_after=retry_after)

    def get_status(self) -> dict[str, Any]:
        result = {}
        for name in list(self._services.keys()):
            current_state = self.get_state(name)
            s = self._services[name]
            result[name] = {
                "state": current_state.value,
                "failure_count": s.failure_count,
                "success_count": s.success_count,
                "remaining_recovery_time": round(self.remaining_recovery_time(name), 2),
            }
        return result
