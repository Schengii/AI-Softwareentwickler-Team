# In main.py sicherstellen:
from app.api.auth import router as auth_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
