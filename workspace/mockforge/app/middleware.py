from datetime import UTC, datetime

# ... (Imports)

class ProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # ... (Request-Handling)
        response = await call_next(request)

        async with AsyncSessionLocal() as db, db.begin():
            log = TrafficLog(
                timestamp=datetime.now(tz=UTC).isoformat(),
                method=request.method,
                url=str(request.url),
                request_headers=str(dict(request.headers)),
                request_body=body_bytes.decode("utf-8", errors="ignore"),
                response_status=response.status_code,
                response_body="",
            )
            db.add(log)
            await db.commit()
        return response
