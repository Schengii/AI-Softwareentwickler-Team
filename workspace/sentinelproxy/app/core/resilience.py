import httpx
from circuitbreaker import circuit
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Retry-Policy für transiente Netzwerkfehler
retry_policy = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)),
    reraise=True
)

# Circuit Breaker Instanz
# Öffnet bei 5 Fehlern, bleibt 30s offen
upstream_circuit = circuit(failure_threshold=5, recovery_timeout=30)
