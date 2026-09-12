"""Host-spezifischer Circuit Breaker zur Vermeidung von Kaskadenausfällen."""

import threading
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlparse


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """In-Memory Circuit Breaker je Host mit Thread-Sicherheit."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._states: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _get_host(self, url: str) -> str:
        return urlparse(url).netloc or url

    def can_execute(self, url: str) -> bool:
        host = self._get_host(url)
        with self._lock:
            info = self._states.get(host)
            if not info:
                return True
            
            state = info.get("state", CircuitState.CLOSED)
            if state == CircuitState.CLOSED:
                return True
            
            now = datetime.now(timezone.utc).timestamp()
            if state == CircuitState.OPEN:
                if now - info.get("last_failure", 0) > self.recovery_timeout:
                    info["state"] = CircuitState.HALF_OPEN
                    return True
                return False
            
            # HALF_OPEN: Probeversuch erlauben
            return True

    def record_success(self, url: str) -> None:
        host = self._get_host(url)
        with self._lock:
            self._states[host] = {
                "state": CircuitState.CLOSED,
                "failure_count": 0,
                "last_failure": 0.0
            }

    def record_failure(self, url: str) -> None:
        host = self._get_host(url)
        with self._lock:
            info = self._states.setdefault(host, {
                "state": CircuitState.CLOSED,
                "failure_count": 0,
                "last_failure": 0.0
            })
            info["failure_count"] += 1
            info["last_failure"] = datetime.now(timezone.utc).timestamp()

            if info["failure_count"] >= self.failure_threshold:
                info["state"] = CircuitState.OPEN


circuit_breaker = CircuitBreaker()
