import time
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from app.models.schemas import DispatchRequest, DispatchResponse
from app.core.security import get_api_key
from app.services.rate_limiter import rate_limiter
from app.services.circuit_breaker import CircuitBreakerManager

router = APIRouter()
cb_manager = CircuitBreakerManager()

@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_request(
    request: DispatchRequest,
    req: Request,
    api_key: str = Depends(get_api_key)
):
    client_ip = req.client.host if req.client else "127.0.0.1"
    
    # Rate Limiting
    try:
        if hasattr(rate_limiter, "acquire"):
            allowed, retry_after = rate_limiter.acquire(client_ip)
        elif hasattr(rate_limiter, "is_allowed"):
            allowed, retry_after = rate_limiter.is_allowed(client_ip)
        else:
            allowed, retry_after = True, 0.0
    except Exception:
        allowed, retry_after = True, 0.0
        
    if not allowed:
        raise HTTPException(
            status_code=429, 
            detail="Too Many Requests", 
            headers={"Retry-After": str(retry_after)}
        )

    # Circuit Breaker
    cb = cb_manager.get_circuit(request.service)
    if hasattr(cb, "can_execute") and not cb.can_execute():
        raise HTTPException(status_code=503, detail="Service Unavailable (Circuit Open)")
    elif hasattr(cb, "is_allowed") and not cb.is_allowed():
        raise HTTPException(status_code=503, detail="Service Unavailable (Circuit Open)")

    url = f"http://{request.target}{request.path}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=url,
                json=request.payload,
                timeout=5.0
            )
            response.raise_for_status()
            
            if hasattr(cb, "record_success"):
                cb.record_success()
            elif hasattr(cb, "on_success"):
                cb.on_success()
                
            return DispatchResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                body=response.json() if "application/json" in response.headers.get("content-type", "") else response.text
            )
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            if hasattr(cb, "record_failure"):
                cb.record_failure()
            elif hasattr(cb, "on_failure"):
                cb.on_failure()
        return DispatchResponse(
            status_code=e.response.status_code,
            headers=dict(e.response.headers),
            body=e.response.json() if "application/json" in e.response.headers.get("content-type", "") else e.response.text
        )
    except Exception as e:
        if hasattr(cb, "record_failure"):
            cb.record_failure()
        elif hasattr(cb, "on_failure"):
            cb.on_failure()
        raise HTTPException(status_code=503, detail=f"Downstream error: {str(e)}")
