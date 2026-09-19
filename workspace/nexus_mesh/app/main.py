import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.logger import log_audit
from app.core.metrics import REQUEST_COUNT, REQUEST_LATENCY, get_metrics_response
from app.core.rate_limiter import RateLimiter
from app.core.security import SecurityHeadersMiddleware
from fastapi.middleware.cors import CORSMiddleware

# Globals
http_client: httpx.AsyncClient | None = None
circuit_breaker: CircuitBreaker | None = None
rate_limiter: RateLimiter | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client, circuit_breaker, rate_limiter
    settings = get_settings()
    
    http_client = httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))
    circuit_breaker = CircuitBreaker(
        failure_threshold=settings.CB_FAILURE_THRESHOLD,
        recovery_timeout=settings.CB_RECOVERY_TIMEOUT
    )
    rate_limiter = RateLimiter(
        capacity=settings.RATE_LIMIT_TOKENS,
        refill_rate=settings.RATE_LIMIT_REFILL_RATE
    )
    
    yield
    
    if http_client:
        await http_client.aclose()

app = FastAPI(title="Nexus Mesh API Gateway", lifespan=lifespan)

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "circuit_breakers": circuit_breaker.get_status() if circuit_breaker else {}
    }

@app.get("/metrics")
async def metrics():
    return get_metrics_response()

@app.api_route("/{service_name}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def gateway_route(service_name: str, path: str, request: Request):
    settings = get_settings()
    
    # 1. Rate Limiting
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter and not rate_limiter.consume(client_ip):
        log_audit("rate_limit_exceeded", {"client_ip": client_ip, "service": service_name})
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too Many Requests")
    
    # 2. Routing Check
    if service_name not in settings.ROUTES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    
    target_base = settings.ROUTES[service_name]
    target_url = f"{target_base}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"
        
    # 3. Circuit Breaker Check
    if circuit_breaker and not circuit_breaker.can_execute(service_name):
        log_audit("circuit_breaker_open", {"service": service_name})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service Unavailable (Circuit Open)")
    
    # 4. Forwarding
    method = request.method
    headers = dict(request.headers)
    headers.pop("host", None) # Remove original host header
    
    body = await request.body()
    
    start_time = time.monotonic()
    try:
        if not http_client:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="HTTP Client not initialized")
            
        response = await http_client.request(
            method=method,
            url=target_url,
            headers=headers,
            content=body,
            timeout=10.0
        )
        
        # Record Success/Failure based on status code
        if circuit_breaker:
            if response.status_code >= 500:
                circuit_breaker.record_failure(service_name)
            else:
                circuit_breaker.record_success(service_name)
            
        # Metrics
        latency = time.monotonic() - start_time
        REQUEST_LATENCY.labels(service=service_name).observe(latency)
        REQUEST_COUNT.labels(service=service_name, method=method, status=response.status_code).inc()
        
        # Audit Log
        log_audit("request_forwarded", {
            "service": service_name,
            "method": method,
            "path": path,
            "status": response.status_code,
            "latency_ms": round(latency * 1000, 2)
        })
        
        # Exclude headers that might cause issues when forwarding back
        excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
        resp_headers = {k: v for k, v in response.headers.items() if k.lower() not in excluded_headers}
        
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=resp_headers
        )
        
    except httpx.RequestError as e:
        if circuit_breaker:
            circuit_breaker.record_failure(service_name)
        log_audit("request_failed", {"service": service_name, "error": str(e)})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Bad Gateway") from e
