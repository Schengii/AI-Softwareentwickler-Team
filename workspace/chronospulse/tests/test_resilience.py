import asyncio
import pytest
from app.utils.resilience import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError,
    ExponentialBackoff,
    AdaptiveBackpressure,
    BackpressureExceededError,
)

@pytest.mark.asyncio
async def test_circuit_breaker_trips_to_open():
    breaker = CircuitBreaker(name="test_cb", failure_threshold=2, recovery_timeout=0.1)

    async def faulty_call():
        raise ConnectionError("Service unreachable")

    # 1. Failure
    with pytest.raises(ConnectionError):
        await breaker.execute(faulty_call)
    assert breaker.state == CircuitState.CLOSED

    # 2. Failure -> Trip to OPEN
    with pytest.raises(ConnectionError):
        await breaker.execute(faulty_call)
    assert breaker.state == CircuitState.OPEN

    # Folgerequest wird sofort per CircuitBreakerOpenError abgewiesen (Fast-Fail)
    with pytest.raises(CircuitBreakerOpenError):
        await breaker.execute(faulty_call)


@pytest.mark.asyncio
async def test_circuit_breaker_recovery_to_half_open():
    breaker = CircuitBreaker(name="test_recover", failure_threshold=1, recovery_timeout=0.05, half_open_max_calls=1)

    async def faulty():
        raise RuntimeError("Fail")

    async def success():
        return "ok"

    with pytest.raises(RuntimeError):
        await breaker.execute(faulty)
    assert breaker.state == CircuitState.OPEN

    await asyncio.sleep(0.06)
    assert breaker.state == CircuitState.HALF_OPEN

    # Erfolgreicher Test-Call im HALF_OPEN Zustand schließt den Breaker wieder
    res = await breaker.execute(success)
    assert res == "ok"
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_exponential_backoff_with_fallback():
    backoff = ExponentialBackoff(base_delay=0.01, max_delay=0.05, max_retries=2, jitter=True)
    calls = 0

    async def failing_op():
        nonlocal calls
        calls += 1
        raise TimeoutError("Remote timeout")

    async def fallback_handler(exc: BaseException):
        return "fallback_value"

    result = await backoff.execute(failing_op, retry_exceptions=(TimeoutError,), fallback=fallback_handler)
    assert result == "fallback_value"
    assert calls == 3  # Initial + 2 Retries


@pytest.mark.asyncio
async def test_adaptive_backpressure_load_shedding():
    bp = AdaptiveBackpressure(max_concurrency=2, queue_capacity=2)

    # 2 Requests belegen die gesamte Kapazität
    await bp.acquire()
    await bp.acquire()

    # 3. Request überschreitet Kapazität -> Load Shedding
    with pytest.raises(BackpressureExceededError):
        async with bp.limit():
            pass

    await bp.release()
    await bp.release()
