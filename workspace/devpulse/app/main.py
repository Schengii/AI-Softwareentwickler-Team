from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.db.session import Base, engine

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: Dispose engine
    await engine.dispose()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

@app.get("/health", tags=["health"])
async def health_check():
    return JSONResponse(content={"status": "ok"})

# Mount static files (Frontend)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# TODO: Include routers here once they are created in app/api/
# app.include_router(api_router, prefix=settings.API_V1_STR)
