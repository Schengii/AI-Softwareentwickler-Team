from fastapi import FastAPI

from app.api.v1.events import router as events_router

app = FastAPI(title="SynapseGate")

app.include_router(events_router, prefix="/api/v1/events", tags=["events"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}
