from fastapi import FastAPI
from app.api.auth import router as auth_router

app = FastAPI(title="OpsPilot API")

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
