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