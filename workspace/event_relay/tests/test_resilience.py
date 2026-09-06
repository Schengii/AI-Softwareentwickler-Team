
import pytest

from app.resilience import resilience


@pytest.mark.asyncio
async def test_retry_mechanism():
    count = 0
    @resilience.retry_with_backoff(retries=3, base_delay=0.1)
    async def failing_func():
        nonlocal count
        count += 1
        if count < 3:
            raise ValueError("Fail")
        return "Success"

    result = await failing_func()
    assert result == "Success"
    assert count == 3

@pytest.mark.asyncio
async def test_circuit_breaker_opens():
    @resilience.circuit_breaker
    async def always_fails():
        raise ConnectionError("Service Down")

    for _ in range(3):
        with pytest.raises(ConnectionError):
            await always_fails()
    
    assert resilience.state == "OPEN"
