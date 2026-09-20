import asyncio
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import ErrorDetail, ErrorEnvelope


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> tuple[bool, int]:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            
            # Refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, int(self.tokens)
            return False, int(self.tokens)

class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()

    async def get_bucket(self, key: str, capacity: int, refill_rate: float) -> TokenBucket:
        async with self._lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(capacity, refill_rate)
            return self._buckets[key]

rate_limiter = RateLimiter()

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        
        # Determine client identifier (IP or Client-ID header)
        client_id = request.headers.get("X-Client-ID")
        if not client_id:
            client_id = request.client.host if request.client else "unknown"
            
        bucket = await rate_limiter.get_bucket(
            client_id, 
            settings.RATE_LIMIT_TOKENS, 
            settings.RATE_LIMIT_REFILL_RATE
        )
        
        allowed, remaining = await bucket.consume(1)
        
        if not allowed:
            reset_time = 1.0 / settings.RATE_LIMIT_REFILL_RATE
            response = JSONResponse(
                status_code=429,
                content=ErrorEnvelope(
                    error=ErrorDetail(
                        code="RATE_LIMIT_EXCEEDED",
                        message="Too many requests."
                    )
                ).model_dump(exclude_none=True)
            )
            response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_TOKENS)
            response.headers["X-RateLimit-Remaining"] = "0"
            response.headers["X-RateLimit-Reset"] = str(int(reset_time))
            return response
            
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_TOKENS)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
