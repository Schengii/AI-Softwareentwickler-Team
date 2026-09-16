from contextlib import asynccontextmanager

from fastapi import FastAPI

from security import setup_security


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup resources can be initialized here
    yield
    # Shutdown resources can be cleaned up here

app = FastAPI(title="Ping Service", lifespan=lifespan)
setup_security(app)

@app.get("/health")
async def health():
    """Health-Check-Endpunkt für Monitoring."""
    return {"status": "ok"}

@app.get("/ping")
async def ping():
    """Ping-Endpunkt, der {'status': 'pong'} zurückgibt."""
    return {"status": "pong"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
