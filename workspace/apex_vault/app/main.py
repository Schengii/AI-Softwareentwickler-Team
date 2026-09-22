from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.base import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="Secrets Vault", version="1.0.0", lifespan=lifespan)

@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}

# Import and include vault router
from app.api.routes_vault import router

app.include_router(router, prefix="/api/v1")
del router

# Import and include audit router
from app.api.routes_audit import router

app.include_router(router, prefix="/api/v1")
del router
