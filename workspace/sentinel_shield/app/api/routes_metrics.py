from fastapi import APIRouter, Depends
from app.core.security import get_api_key
from app.services.rate_limiter import rate_limiter
from app.services.circuit_breaker import CircuitBreakerManager

router = APIRouter()
cb_manager = CircuitBreakerManager()

@router.get("/metrics")
async def get_metrics(api_key: str = Depends(get_api_key)):
    rl_metrics = {}
    if hasattr(rate_limiter, "get_metrics"):
        rl_metrics = rate_limiter.get_metrics()
    elif hasattr(rate_limiter, "metrics"):
        rl_metrics = rate_limiter.metrics
        
    cb_metrics = {}
    if hasattr(cb_manager, "get_all_states"):
        cb_metrics = cb_manager.get_all_states()
        
    return {
        "rate_limiter": rl_metrics,
        "circuit_breakers": cb_metrics,
        "status": "ok"
    }
