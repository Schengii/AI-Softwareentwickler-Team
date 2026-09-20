import asyncio


class IdempotencyEngine:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def acquire(self, key: str) -> bool:
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
        
        # Versuche Lock zu bekommen, ohne zu warten (non-blocking für Idempotenz-Check)
        if self._locks[key].locked():
            return False
        await self._locks[key].acquire()
        return True

    async def release(self, key: str):
        if key in self._locks and self._locks[key].locked():
            self._locks[key].release()

    async def get_result(self, key: str) -> dict | None:
        # Placeholder for result storage if needed
        return None

idempotency_engine = IdempotencyEngine()

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.errors import ErrorDetail, ErrorEnvelope


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in ["POST", "PUT", "PATCH"]:
            return await call_next(request)
            
        idempotency_key = request.headers.get("X-Idempotency-Key")
        if not idempotency_key:
            return await call_next(request)
            
        acquired = await idempotency_engine.acquire(idempotency_key)
        if not acquired:
            return JSONResponse(
                status_code=409,
                content=ErrorEnvelope(
                    error=ErrorDetail(
                        code="CONCURRENT_REQUEST",
                        message="A request with this idempotency key is already being processed."
                    )
                ).model_dump(exclude_none=True)
            )
            
        try:
            response = await call_next(request)
            return response
        finally:
            await idempotency_engine.release(idempotency_key)
