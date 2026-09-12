# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Queue-Worker, DB-Pool
    yield
    # Shutdown: Worker stoppen, Ressourcen freigeben

app = FastAPI(title="OmniQueue", version="1.0.0", lifespan=lifespan)

@app.get("/health")
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

app.mount("/static", StaticFiles(directory="static"), name="static")
