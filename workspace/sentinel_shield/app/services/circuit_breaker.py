import time
from typing import Dict
from app.models.schemas import CircuitState
from app.core.config import get_settings

class CircuitBreaker:
    def __init__(self):
        self.state = CircuitState.closed
        self.failures = 0
        self.last_failure_time = 0.0
        
class CircuitBreakerManager:
    def __init__(self):
        self.breakers: Dict[str, CircuitBreaker] = {}
        
    def get_breaker(self, service: str) -> CircuitBreaker:
        if service not in self.breakers:
            self.breakers[service] = CircuitBreaker()
        return self.breakers[service]
        
    def record_failure(self, service: str):
        settings = get_settings()
        breaker = self.get_breaker(service)
        breaker.failures += 1
        breaker.last_failure_time = time.monotonic()
        if breaker.failures >= settings.CIRCUIT_FAILURE_THRESHOLD:
            breaker.state = CircuitState.open
            
    def record_success(self, service: str):
        breaker = self.get_breaker(service)
        breaker.failures = 0
        breaker.state = CircuitState.closed
        
    def can_execute(self, service: str) -> bool:
        settings = get_settings()
        breaker = self.get_breaker(service)
        
        if breaker.state == CircuitState.closed:
            return True
            
        if breaker.state == CircuitState.open:
            now = time.monotonic()
            if now - breaker.last_failure_time > settings.CIRCUIT_RECOVERY_TIMEOUT:
                breaker.state = CircuitState.half_open
                return True
            return False
            
        if breaker.state == CircuitState.half_open:
            return True
            
        return False

circuit_manager = CircuitBreakerManager()
