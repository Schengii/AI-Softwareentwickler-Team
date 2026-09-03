from datetime import datetime

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.models import AsyncSessionLocal, TrafficLog


class ProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Body lesen und Stream wiederherstellen
        body_bytes = await request.body()
        async def receive():
            return {"type": "http.request", "body": body_bytes}
        request._receive = receive

        response = await call_next(request)

        # Asynchrones Logging mit AsyncSession
        async with AsyncSessionLocal() as db:
            async with db.begin():
                log = TrafficLog(
                    timestamp=datetime.utcnow().isoformat(),
                    method=request.method,
                    url=str(request.url),
                    request_headers=str(dict(request.headers)),
                    request_body=body_bytes.decode('utf-8', errors='ignore'),
                    response_status=response.status_code,
                    response_body="" # Optional: Response Body hier loggen, erfordert Response-Stream-Handling
                )
                db.add(log)
                await db.commit()
            
        return response
