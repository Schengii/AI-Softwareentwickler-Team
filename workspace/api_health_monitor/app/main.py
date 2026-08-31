import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from app.schemas import CheckCreate
from app.monitor.checker import monitor

app = FastAPI()

@app.get("/checks")
async def get_checks():
    return list(monitor.checks.values())

@app.post("/checks")
async def create_check(check: CheckCreate):
    return monitor.add_check(check)

@app.delete("/checks/{check_id}")
async def delete_check(check_id: str):
    return {"deleted": monitor.checks.pop(check_id, None) is not None}

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    monitor.subscribers.add(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        monitor.subscribers.remove(websocket)
