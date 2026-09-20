import json
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("synapsegate.security")
logger.setLevel(logging.INFO)

# Set of keys that should be masked in logs
SENSITIVE_KEYS = {"auth_token", "user_id", "password", "authorization", "x-api-key", "token", "secret", "cookie"}

def mask_sensitive_data(data: dict) -> dict:
    """
    Recursively masks sensitive values in a dictionary based on SENSITIVE_KEYS.
    """
    masked = {}
    for k, v in data.items():
        if k.lower() in SENSITIVE_KEYS:
            masked[k] = "***MASKED***"
        elif isinstance(v, dict):
            masked[k] = mask_sensitive_data(v)
        elif isinstance(v, list):
            masked[k] = [mask_sensitive_data(i) if isinstance(i, dict) else i for i in v]
        else:
            masked[k] = v
    return masked

class SecurityLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log HTTP requests and responses in JSON format,
    ensuring that sensitive data (like auth headers) is masked.
    """
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start_time = time.monotonic()
        
        # Extract and mask headers
        headers = dict(request.headers)
        masked_headers = mask_sensitive_data(headers)
        
        response = None
        try:
            response = await call_next(request)
        finally:
            process_time = time.monotonic() - start_time
            log_data = {
                "method": request.method,
                "url": str(request.url),
                "headers": masked_headers,
                "client_ip": request.client.host if request.client else None,
                "process_time_ms": round(process_time * 1000, 2),
                "status_code": response.status_code if response else 500,
            }
            logger.info(json.dumps(log_data))
            
        return response
