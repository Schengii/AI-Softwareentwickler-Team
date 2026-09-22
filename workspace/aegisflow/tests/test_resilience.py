import asyncio

import pytest

from app.core.resilience import (
    CircuitBreaker,
    calculate_backoff_with_jitter,
    execute_with_resilience,
)


@pytest.mark.asyncio
async def test_backoff_jitter_bounds():
    for attempt in range(4):
        delay = calculate_backoff_with_jitter(attempt, base_delay=0.2, max_delay=5.0)
        assert 0.1 <= delay <= 5.0

@pytest.mark.asyncio
async def test_circuit_breaker_tripping_and_recovery():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
    assert cb.can_attempt() is True
    
    cb.record_failure()
    assert cb.can_attempt() is True
    assert cb.state == "CLOSED"
    
    cb.record_failure()
    assert cb.state == "OPEN"
    assert cb.can_attempt() is False
    
    # Cooldown abwarten
    await asyncio.sleep(0.12)
    assert cb.can_attempt() is True
    assert cb.state == "HALF_OPEN"
    
    cb.record_success()
    assert cb.state == "CLOSED"

@pytest.mark.asyncio
async def test_execute_with_resilience_exhaustion():
    calls = 0
    async def failing_target():
        nonlocal calls
        calls += 1
        raise ConnectionResetError("Connection dropped by peer")

    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)
    success, _, err = await execute_with_resilience(
        failing_target,
        circuit_breaker=cb,
        max_retries=3,
        base_delay=0.01,
        max_delay=0.05,
    )
    assert success is False
    assert calls == 3
    assert "ConnectionResetError" in err
    assert cb.state == "OPEN"
