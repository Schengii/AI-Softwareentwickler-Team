import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from pybreaker import CircuitBreaker, CircuitBreakerError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

# Logger für Resilienz-Events
logger = logging.getLogger("resilience")

# Circuit Breaker Instanz
# Fail after 3 consecutive failures, reset after 60 seconds
ai_service_breaker = CircuitBreaker(fail_max=3, reset_timeout=60)

def resilience_wrapper(
    fallback_factory: Callable[..., Any] | None = None,
) -> Callable[[Callable], Callable]:
    """
    Kombiniert Circuit Breaker und Retry-Logik mit exponentiellem Backoff.

    Args:
        fallback_factory: Wird bei offenem Circuit Breaker mit den ursprünglichen
            Aufrufargumenten (*args, **kwargs) aufgerufen und muss ein Objekt
            erzeugen, das exakt dem Rückgabetyp der dekorierten Funktion
            entspricht (z. B. ein Pydantic-Modell statt eines rohen Dicts).
            Wird kein `fallback_factory` übergeben, wird ein einfaches
            Status-Dict zurückgegeben (Legacy-Verhalten für Funktionen ohne
            typisierten Rückgabewert).
    """

    def decorator(func: Callable) -> Callable:
        # Retry-Logik: 3 Versuche, exponentieller Backoff mit Jitter
        retry_decorator = retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=1, max=10),
            retry=retry_if_exception_type((asyncio.TimeoutError, Exception)),
            reraise=True
        )

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                # WICHTIG: `call_async` (nicht `call`) verwenden, da `func` eine
                # Coroutine-Funktion ist. `call()` würde die Coroutine lediglich
                # erzeugen statt sie auszuführen — dadurch würden Fehlschläge nie
                # gezählt und der Circuit Breaker nie öffnen.
                return await ai_service_breaker.call_async(
                    retry_decorator(func), *args, **kwargs
                )
            except CircuitBreakerError:
                logger.error("Circuit Breaker open: AI service unavailable")
                # Fallback-Logik: Rückgabe eines typsicheren Standard-Werts bei Ausfall
                if fallback_factory is not None:
                    return fallback_factory(*args, **kwargs)
                return {"status": "fallback", "recommendation": "manual_review_required"}
            except Exception as e:
                logger.error(f"Service call failed after retries: {e}")
                raise

        return wrapper

    return decorator
