class EndpointCircuitBreaker:
    """
    In-Memory Circuit Breaker pro Endpoint-URL.
    Zustände: CLOSED (normal), OPEN (blockiert Aufrufe), HALF_OPEN (Probe-Request).
    Nutzt time.monotonic() für Zeitmessungen.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count: int = 0
        self.state: str = "CLOSED"
        self.last_failure_time: float = 0.0

    def can_attempt(self) -> bool:
        now = time.monotonic()
        if self.state == "OPEN":
            if now - self.last_failure_time >= self.cooldown_seconds:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"