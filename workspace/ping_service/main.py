from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown

app = FastAPI(title="Ping Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://trusted.example.com"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ping")
async def ping():
    return {"status": "pong"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
