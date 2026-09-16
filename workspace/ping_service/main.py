import contextlib

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown

app = FastAPI(title="Ping Service", lifespan=lifespan)

# CORS Middleware - Explizite Whitelist statt Wildcard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Entferne Server-Header, falls von Uvicorn gesetzt (Uvicorn setzt ihn normalerweise als "uvicorn")
    if "server" in response.headers:
        del response.headers["server"]
    return response

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

@app.get("/ping")
async def ping():
    """Ping endpoint."""
    return {"status": "pong"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ping_service.main:app", host="127.0.0.1", port=8000, reload=True)
