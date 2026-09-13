from fastapi import APIRouter

router = APIRouter()

@router.get("/ping", tags=["System"], summary="Ping-Endpunkt")
async def ping() -> dict[str, str]:
    """Einfacher Ping-Endpunkt."""
    return {"ping": "pong"}
