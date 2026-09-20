from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.db.session import engine, Base
from app.api.workflows import router as workflows_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup
    await engine.dispose()

app = FastAPI(
    title="ChronosVault API",
    description="State-Machine-Engine für mehrstufige Workflows mit kryptographischer Audit-Verkettung",
    version="1.0.0",
    lifespan=lifespan
)

# CORS setup (dynamic from settings in real world, allowing all for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

app.include_router(workflows_router)
