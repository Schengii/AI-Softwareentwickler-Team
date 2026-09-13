# app/api/v1/circuit_breaker.py
from fastapi import APIRouter

# Lokales Modul/Paket erstellt, das in app/main.py importiert wird
router = APIRouter(prefix="/circuit-breaker", tags=["Circuit Breaker"])

@router.get("/status")
async def circuit_breaker_status():
    return {"status": "active"}
