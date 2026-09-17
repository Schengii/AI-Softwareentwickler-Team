import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1 import audit, documents
from app.db.base import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup
    await engine.dispose()

app = FastAPI(title="DocuGuard", lifespan=lifespan)

app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(audit.router, prefix="/api/v1/audit", tags=["Audit"])

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}

# Mount public directory for frontend
os.makedirs("public", exist_ok=True)
app.mount("/", StaticFiles(directory="public", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
