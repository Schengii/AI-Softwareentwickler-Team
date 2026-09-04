# app/middleware/rate_limit.py
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class SimpleRateLimiter(BaseHTTPMiddleware):
    """In‑Memory rate limiter – für Demo‑Umgebungen ausreichend."""
    def __init__(self, app, calls: int = 5, period: int = 60):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.history: dict[str, list[float]] = {}

    async def dispatch(self, request, call_next):
        client = request.client.host
        now = time.time()
        timestamps = self.history.get(client, [])
        # keep only timestamps innerhalb des Zeitfensters
        timestamps = [t for t in timestamps if now - t < self.period]
        if len(timestamps) >= self.calls:
            return JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(int(self.period))}
            )
        timestamps.append(now)
        self.history[client] = timestamps
        response = await call_next(request)
        return response

class RateLimitMiddleware(SimpleRateLimiter):
    """Alias für SimpleRateLimiter zur Kompatibilität mit app/main.py."""
