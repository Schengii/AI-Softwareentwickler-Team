from fastapi import FastAPI, HTTPException

from app.kafka_client import kafka_manager
from app.resilience import resilience

app = FastAPI()

@app.post("/events")
async def create_event(topic: str, payload: dict):
    try:
        result = resilience.execute(kafka_manager.send_event, topic, payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
