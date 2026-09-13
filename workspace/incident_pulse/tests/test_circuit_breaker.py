import httpx
import pytest

from app.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenException,
    CircuitState,
    WebhookClient,
)


@pytest.mark.asyncio
async def test_circuit_breaker_transitions_to_open_on_consecutive_failures():
    cb = CircuitBreaker(name="test_breaker", failure_threshold=2, recovery_timeout=0.2)
    
    async def failing_call():
        raise httpx.ConnectError("Service Down")

    # 1. Fehlschlag
    with pytest.raises(httpx.ConnectError):
        await cb.call(failing_call)
    assert cb.state == CircuitState.CLOSED

    # 2. Fehlschlag -> Schwelle erreicht -> OPEN
    with pytest.raises(httpx.ConnectError):
        await cb.call(failing_call)
    assert cb.state == CircuitState.OPEN

    # 3. Direkte Ablehnung ohne Ausführung
    with pytest.raises(CircuitBreakerOpenException):
        await cb.call(failing_call)

@pytest.mark.asyncio
async def test_circuit_breaker_graceful_fallback_and_dlq():
    cb = CircuitBreaker(name="test_dlq_breaker", failure_threshold=1, recovery_timeout=1.0)
    client = WebhookClient(circuit_breaker=cb, timeout=0.1, max_retries=1)

    result = await client.send_webhook("https://unreachable.external.service/hook", {"event": "incident_created"})
    assert result["status"] == 202
    assert result["degraded"] is True

    dlq = await cb.cache.get_dlq()
    assert len(dlq) == 1
    assert dlq[0]["data"]["event"] == "incident_created"
