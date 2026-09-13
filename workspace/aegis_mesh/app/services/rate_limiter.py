import time
from threading import Lock

from app.core.config import get_settings


class RateLimiter:
    """Thread-sicherer Token Bucket Rate Limiter (In-Memory)."""
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens: dict[str, float] = {}
        self.last_refill: dict[str, float] = {}
        self.lock = Lock()

    def is_allowed(self, client_id: str) -> bool:
        """Prüft, ob ein Request für die gegebene client_id erlaubt ist."""
        with self.lock:
            now = time.time()
            if client_id not in self.tokens:
                self.tokens[client_id] = float(self.capacity)
                self.last_refill[client_id] = now

            # Tokens auffüllen basierend auf vergangener Zeit
            elapsed = now - self.last_refill[client_id]
            refill_amount = elapsed * self.refill_rate
            self.tokens[client_id] = min(float(self.capacity), self.tokens[client_id] + refill_amount)
            self.last_refill[client_id] = now

            # Token abziehen falls vorhanden
            if self.tokens[client_id] >= 1.0:
                self.tokens[client_id] -= 1.0
                return True
            return False

def get_rate_limiter() -> RateLimiter:
    """Factory-Funktion für den Rate Limiter."""
    settings = get_settings()
    return RateLimiter(
        capacity=settings.RATE_LIMIT_CAPACITY,
        refill_rate=settings.RATE_LIMIT_REFILL_RATE
    )
