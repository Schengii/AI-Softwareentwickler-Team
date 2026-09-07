from fastapi import FastAPI

from app.core.config import settings
from app.core.security import configure_security

app = FastAPI(title=settings.PROJECT_NAME, openapi_url=f"{settings.API_V1_STR}/openapi.json")

configure_security(app)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get(f"{settings.API_V1_STR}/vehicles")
async def get_vehicles():
    # Platzhalter für Datenbank-Abfrage
    return {"vehicles": []}
