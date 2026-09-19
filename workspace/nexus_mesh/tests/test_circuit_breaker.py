
import pytest

# Mock-Klassen für den Circuit Breaker, um die Logik zu testen,
# bevor die echte Implementierung in app/core/circuit_breaker.py fertig ist.

class CircuitBreaker:
    def __init__(self):
        self.state = "CLOSED"
    
    def record_failure(self):
        self.state = "OPEN"

@pytest.mark.asyncio
async def test_circuit_breaker_state_change():
    cb = CircuitBreaker()
    assert cb.state == "CLOSED"
    cb.record_failure()
    assert cb.state == "OPEN"
