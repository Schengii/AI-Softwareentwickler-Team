import asyncio
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Secure Random Instance for Jitter compliant with security guidelines
_sys_random = secrets.SystemRandom()


def calculate_backoff_delay(
    retry_count: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    factor: float = 2.0,
    jitter: bool = True,
) -> float:
    """Berechnet exponentielles Backoff mit Jitter (Full/Decorrelated Jitter).

    Formel: min(max_delay, base_delay * (factor ** retry_count)) * jitter_factor
    """
    raw_delay = min(max_delay, base_delay * (factor ** max(0, retry_count)))
    if not jitter or raw_delay <= 0:
        return raw_delay

    # Full Jitter: Uniform distribution in [0.8 * raw_delay, 1.2 * raw_delay]
    jitter_factor = _sys_random.uniform(0.8, 1.2)  # nosec B311
    return round(min(max_delay, raw_delay * jitter_factor), 3)


def get_next_retry_time(
    retry_count: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    factor: float = 2.0,
) -> datetime:
    """Gibt den nächsten Retry-Zeitpunkt als timezone-aware datetime zurück."""
    delay = calculate_backoff_delay(
        retry_count=retry_count,
        base_delay=base_delay,
        max_delay=max_delay,
        factor=factor,
        jitter=True,
    )
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


class ExecutionTimeoutError(Exception):
    """Wird ausgelöst, wenn eine Job-Ausführung das Zeitlimit überschreitet."""


async def run_with_timeout(
    coro_fn: Callable[..., Any],
    timeout_seconds: float = 30.0,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Führt eine asynchrone Funktion mit striktem Timeout aus."""
    try:
        return await asyncio.wait_for(coro_fn(*args, **kwargs), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise ExecutionTimeoutError(f"Job execution timed out after {timeout_seconds}s") from exc
