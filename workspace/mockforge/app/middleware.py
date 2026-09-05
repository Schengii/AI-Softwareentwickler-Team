from datetime import datetime, timezone

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.models import AsyncSessionLocal, TrafficLog


class ProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        body_bytes = await request.body()
        async def receive():
            return {"type": "http.request", "body": body_bytes}
        request._receive = receive

        response = await call_next(request)

        try:
            async with AsyncSessionLocal() as db, db.begin():
                log = TrafficLog(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    method=request.method,
                    url=str(request.url),
                    request_headers=str(dict(request.headers)),
                    request_body=body_bytes.decode("utf-8", errors="ignore"),
                    response_status=response.status_code,
                    response_body="",
                )
                db.add(log)
                await db.commit()
        except Exception:
            # Logging-Integration empfohlen, hier silent fail um Request-Flow zu schützen
            pass
            
        return response
