import asyncio
from datetime import datetime, timezone

import pytest

from app.core.resilience import (
    ExecutionTimeoutError,
    calculate_backoff_delay,
    get_next_retry_time,
    run_with_timeout,
)


def test_exponential_backoff_progression():
    """Prüft exponentiellen Anstieg des Delays über mehrere Retries."""
    delays = [calculate_backoff_delay(retry_count=i, base_delay=1.0, factor=2.0, jitter=False) for i in range(5)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

def test_backoff_jitter_and_cap():
    """Stellt sicher, dass Jitter variiert und max_delay nicht überschritten wird."""
    max_delay = 10.0
    for _ in range(20):
        delay = calculate_backoff_delay(retry_count=10, base_delay=1.0, max_delay=max_delay, jitter=True)
        assert 0.0 < delay <= max_delay

def test_get_next_retry_time_future():
    """Validiert, dass next_retry_at in der Zukunft liegt."""
    now = datetime.now(timezone.utc)
    next_retry = get_next_retry_time(retry_count=1, base_delay=2.0)
    assert next_retry > now

@pytest.mark.asyncio
async def test_run_with_timeout_success():
    async def fast_task():
        return "success"
    res = await run_with_timeout(fast_task, timeout_seconds=1.0)
    assert res == "success"

@pytest.mark.asyncio
async def test_run_with_timeout_trigger():
    async def slow_task():
        await asyncio.sleep(0.5)
    with pytest.raises(ExecutionTimeoutError):
        await run_with_timeout(slow_task, timeout_seconds=0.05)
