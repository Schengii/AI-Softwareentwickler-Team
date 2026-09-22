import time
import threading
from typing import Dict, Tuple

class TokenBucketRateLimiter:
    """
    Thread-safe In-Memory Token-Bucket & Sliding-Window Rate Limiter.
    Nutzt time.monotonic() für zuverlässige Zeitmessung ohne Event-Loop-Abhängigkeiten.
    """
    def __init__(self, default_rate: int = 10, default_capacity: int = 10, window_size: int = 60):
        self.default_rate = default_rate  # tokens per window
        self.default_capacity = default_capacity
        self.window_size = window_size
        self._lock = threading.Lock()
        # client_id -> (tokens, last_refill_timestamp)
        self._buckets: Dict[str, Tuple[float, float]] = {}
        # client_id -> list of request timestamps for sliding window tracking
        self._sliding_windows: Dict[str, list] = {}

    def is_allowed(self, client_id: str, tokens: int = 1, capacity: int | None = None, rate: int | None = None) -> bool:
        cap = capacity if capacity is not None else self.default_capacity
        refill_rate = (rate if rate is not None else self.default_rate) / float(self.window_size)
        now = time.monotonic()

        with self._lock:
            current_tokens, last_refill = self._buckets.get(client_id, (float(cap), now))
            
            # Refill tokens based on elapsed time
            elapsed = max(0.0, now - last_refill)
            current_tokens = min(float(cap), current_tokens + elapsed * refill_rate)
            
            if current_tokens >= tokens:
                current_tokens -= tokens
                self._buckets[client_id] = (current_tokens, now)
                
                # Also track sliding window
                timestamps = self._sliding_windows.setdefault(client_id, [])
                cutoff = now - self.window_size
                self._sliding_windows[client_id] = [t for t in timestamps if t > cutoff] + [now]
                return True
            else:
                self._buckets[client_id] = (current_tokens, now)
                return False

    def reset(self, client_id: str | None = None) -> None:
        with self._lock:
            if client_id:
                self._buckets.pop(client_id, None)
                self._sliding_windows.pop(client_id, None)
            else:
                self._buckets.clear()
                self._sliding_windows.clear()

    def get_remaining_tokens(self, client_id: str) -> float:
        with self._lock:
            now = time.monotonic()
            if client_id not in self._buckets:
                return float(self.default_capacity)
            current_tokens, last_refill = self._buckets[client_id]
            refill_rate = self.default_rate / float(self.window_size)
            elapsed = max(0.0, now - last_refill)
            return min(float(self.default_capacity), current_tokens + elapsed * refill_rate)

rate_limiter = TokenBucketRateLimiter()
