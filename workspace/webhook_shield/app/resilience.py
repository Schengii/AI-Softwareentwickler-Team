import logging

import httpx
from pybreaker import CircuitBreaker
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

# Circuit Breaker konfiguriert für Webhook-Ziele
webhook_breaker = CircuitBreaker(fail_max=5, reset_timeout=60)

logger = logging.getLogger(__name__)

@retry(
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True
)
@webhook_breaker
async def forward_webhook(url: str, payload: dict, headers: dict):
    """
    Sendet Webhook mit Retry-Logik (Backoff + Jitter) und Circuit Breaker.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response
