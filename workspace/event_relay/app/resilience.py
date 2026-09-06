import asyncio
import logging
import random
from collections.abc import Callable
from functools import wraps

logger = logging.getLogger(__name__)

class ResilienceManager:
    """Circuit Breaker & Retry Logic with Exponential Backoff + Jitter."""
    
    def __init__(self, failure_threshold=3, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED"

    def retry_with_backoff(self, retries=3, base_delay=1):
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                for i in range(retries):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        if i == retries - 1:
                            raise e
                        delay = (base_delay * 2 ** i) + (random.uniform(0, 1) * 0.1)
                        logger.warning(f"Retry {i+1}/{retries} after {delay:.2f}s due to {e}")
                        await asyncio.sleep(delay)
            return wrapper
        return decorator

    def circuit_breaker(self, func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if (asyncio.get_event_loop().time() - self.last_failure_time) > self.recovery_timeout:
                    self.state = "HALF-OPEN"
                else:
                    raise Exception("Circuit Breaker is OPEN")
            
            try:
                result = await func(*args, **kwargs)
                self.failures = 0
                self.state = "CLOSED"
                return result
            except Exception as e:
                self.failures += 1
                self.last_failure_time = asyncio.get_event_loop().time()
                if self.failures >= self.failure_threshold:
                    self.state = "OPEN"
                raise e
        return wrapper

resilience = ResilienceManager()
