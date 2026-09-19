class RateLimiter:
    def __init__(self, capacity: int = 100, refill_rate: float = 10.0):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.buckets: dict[str, TokenBucket] = {}

    def consume(self, key: str, tokens: int = 1) -> bool:
        now = time.monotonic()
        if key not in self.buckets:
            self.buckets[key] = TokenBucket(tokens=float(self.capacity), last_update=now)
        
        bucket = self.buckets[key]
        
        # Refill
        elapsed = now - bucket.last_update
        bucket.tokens = min(float(self.capacity), bucket.tokens + elapsed * self.refill_rate)
        bucket.last_update = now
        
        if bucket.tokens >= tokens:
            bucket.tokens -= tokens
            return True
        return False